"""Skan obszaru modelem bez sieci i bez bazy: transport podaje atrapa httpx, dane — FakePool.

Wiekszosc testow dotyka `analysis_from_model` wprost, bo cala tresc tego endpointu to szesc
licznikow, a licznik da sie sprawdzic tylko na przykladzie policzonym recznie. Ksztalt odpowiedzi
modelu jest przepisany z odpowiedzi zywej instancji (FeatureCollection, `source_id`, `status`,
`asbestos_probability`, `meta.model_id`), a nie z wyobrazenia o niej.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.area import MAX_AREA_KM2, BoundingBox, bbox_area_km2, format_km2
from app.area_analysis import (
    BUILDING_COUNT_SQL,
    BUILDING_FACTS_SQL,
    BuildingFacts,
    analysis_from_model,
    corners,
    count_buildings,
    model_limit_problem,
    read_building_facts,
)
from app.config import Settings
from app.main import create_app
from app.prediction import (
    MODEL_MAX_AREA_KM2,
    MODEL_MAX_BUILDINGS,
    SUSPECTED_THRESHOLD,
    AreaModelResult,
    HttpModelProvider,
    ModelBuilding,
)
from app.routes import area as area_routes
from tests.test_prediction import affirmative_claims

MODEL_ID = "70b702e1922493f0b57be82240f651ea2509f6bc2e35bdf0048017bcfe93d67c"
ANALYZE_PATH = "/api/area/analyze"

# Prostokat pod Zwoleniem, ten sam, na ktorym sprawdzalismy endpoint na zywo: 74 budynki, wiec
# miesci sie w limicie modelu (100 budynkow, 4 km2).
SMALL_SELECTION = {"sw": {"lng": 21.5745, "lat": 51.3555}, "ne": {"lng": 21.578, "lat": 51.358}}
# ~19 km2: przechodzi bramke skanu rejestru (25 km2), ale nie bramke modelu (4 km2).
HUGE_SELECTION = {"sw": {"lng": 21.50, "lat": 51.30}, "ne": {"lng": 21.55, "lat": 51.35}}

SETTINGS = Settings(database_url="postgresql://unused", prediction_provider="mock")

POLYGON = {"type": "Polygon", "coordinates": [[[21.5745, 51.3555], [21.5746, 51.3555], [21.5746, 51.3556]]]}
MULTIPOLYGON = {"type": "MultiPolygon", "coordinates": [[[[21.5, 51.3], [21.6, 51.3], [21.6, 51.4]]]]}


# --- atrapy transportu i bazy -------------------------------------------------------------------


def feature(
    source_id: int,
    probability: float | None = 0.72,
    status: str = "ok",
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": POLYGON if geometry is None else geometry,
        "properties": {"source_id": str(source_id), "status": status, "asbestos_probability": probability},
    }


def collection(*features: dict[str, Any], model_id: str | None = MODEL_ID) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(features), "meta": {"model_id": model_id}}


def responder(payload: dict[str, Any], status_code: int = 200, headers: dict[str, str] | None = None):
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code, json=payload, headers=headers or {})

    return seen, handle


def provider_with(handler: Any) -> HttpModelProvider:
    """Dostawca gadajacy z atrapa transportu; zegar jest wstrzykiwany, wiec testy nie spia."""
    return HttpModelProvider(
        base_url="http://model.example",
        token="token-testowy",
        transport=httpx.MockTransport(handler),
        min_interval_s=0.0,
        clock=lambda: 1000.0,
    )


class FakeCursor:
    def __init__(self, rows: Sequence[Sequence[Any]]) -> None:
        self.rows = list(rows)

    async def fetchone(self) -> Sequence[Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[Sequence[Any]]:
        return list(self.rows)


class FakeConnection:
    def __init__(self, pool: "FakePool") -> None:
        self.pool = pool

    async def execute(self, sql: str, params: Any = None) -> FakeCursor:
        self.pool.statements.append((sql, params))
        if "count(*)" in sql:
            return FakeCursor([(self.pool.count,)])
        return FakeCursor(self.pool.facts)


class FakePool:
    """Pula bez bazy: liczba budynkow dla bramki i wiersze faktow dla dopasowania po `osm_id`.

    Wiersz faktow ma ten sam ksztalt co BUILDING_FACTS_SQL: (osm_id, area_m2, listed).
    """

    def __init__(
        self,
        count: int = 0,
        facts: Sequence[tuple[int, float | None, bool]] = (),
        error: BaseException | None = None,
    ) -> None:
        self.count = count
        self.facts = list(facts)
        self.error = error
        self.statements: list[tuple[str, Any]] = []

    async def open(self, wait: bool = False) -> None:
        return None

    async def close(self) -> None:
        return None

    @asynccontextmanager
    async def connection(self, timeout: float | None = None) -> AsyncIterator[FakeConnection]:
        if self.error is not None:
            raise self.error
        yield FakeConnection(self)


def client_with(pool: FakePool, handler: Any = None) -> TestClient:
    app = create_app(SETTINGS, pool_factory=lambda _settings: pool)
    if ANALYZE_PATH not in {getattr(route, "path", None) for route in app.routes}:
        app.include_router(area_routes.router, prefix="/api")
    if handler is not None:
        app.state.roof_provider = provider_with(handler)
    return TestClient(app)


def selection(payload: dict[str, dict[str, float]]) -> BoundingBox:
    return BoundingBox(
        south=payload["sw"]["lat"],
        west=payload["sw"]["lng"],
        north=payload["ne"]["lat"],
        east=payload["ne"]["lng"],
    )


# --- przyklad policzony recznie ------------------------------------------------------------------
#
# Osiem budynkow z ocena i dwa bez niej. Prog to 0,5, wiec podejrzane sa 101, 102, 103 (dokladnie
# na progu) i 107. Z nich zgloszony jest tylko 102, czyli suspectedNotListed = 3. Zgloszone
# i nizej progu: 104 i 106, czyli listedNotSuspected = 2. Budynek 110 jest zgloszony, ale bez
# oceny — nie wchodzi do zadnego z tych dwoch licznikow, bo „nie wiemy" to nie „model nie widzi".
HAND_COUNTED = (
    # (osm_id, probability, listed, area_m2)
    (101, 0.91, False, 120.0),
    (102, 0.80, True, 200.5),
    (103, 0.50, False, 80.0),
    (104, 0.49, True, 50.0),
    (105, 0.30, False, 10.0),
    (106, 0.10, True, 60.0),
    (107, 0.72, False, 31.0),
    (108, 0.05, False, 15.0),
)
NO_SCORE = ((109, "low_quality"), (110, "imagery_error"))
SUSPECTED_AREA_M2 = 120.0 + 200.5 + 80.0 + 31.0  # 431,5 m2 — tylko podejrzane dachy


def hand_counted_result() -> AreaModelResult:
    buildings = [
        ModelBuilding(osm_id=osm_id, status="ok", probability=probability, geometry=POLYGON)
        for osm_id, probability, _listed, _area in HAND_COUNTED
    ]
    buildings += [
        ModelBuilding(osm_id=osm_id, status=status, probability=None, geometry=POLYGON) for osm_id, status in NO_SCORE
    ]
    return AreaModelResult(model_name=MODEL_ID, buildings=buildings)


def facts_for(*osm_ids: int, listed: bool = False, area_m2: float = 100.0) -> dict[int, BuildingFacts]:
    """Nasza baza zna te budynki. Wymagane wszedzie tam, gdzie test patrzy na liste wynikow:
    budynek nieznany bazie jest swiadomie pomijany, bo o jego statusie rejestrowym nic nie wiemy."""
    return {osm_id: BuildingFacts(area_m2=area_m2, listed=listed) for osm_id in osm_ids}


def hand_counted_facts() -> dict[int, BuildingFacts]:
    facts = {osm_id: BuildingFacts(area_m2=area, listed=listed) for osm_id, _probability, listed, area in HAND_COUNTED}
    # Budynek bez oceny tez jest w naszej bazie i tez bywa zgloszony — a mimo to nie ma go
    # w zadnym liczniku poza `noResult`.
    facts[110] = BuildingFacts(area_m2=90.0, listed=True)
    facts[109] = BuildingFacts(area_m2=40.0, listed=False)
    return facts


# --- liczniki -------------------------------------------------------------------------------------


def test_all_six_counters_on_a_hand_counted_example() -> None:
    stats = analysis_from_model(hand_counted_result(), hand_counted_facts()).stats

    assert (stats.analysed, stats.no_result) == (8, 2)
    assert stats.suspected == 4
    assert stats.suspected_not_listed == 3  # najwazniejsza liczba w calej aplikacji
    assert stats.suspected_listed == 1
    assert stats.listed_not_suspected == 2
    assert stats.suspected_roof_area_m2 == SUSPECTED_AREA_M2


def test_the_two_halves_of_suspected_always_add_up() -> None:
    """Kierunek tych dwoch licznikow latwo pomylic, wiec pilnuje go niezmiennik."""
    stats = analysis_from_model(hand_counted_result(), hand_counted_facts()).stats

    assert stats.suspected_listed + stats.suspected_not_listed == stats.suspected


def test_the_share_is_counted_against_the_scored_buildings_not_all_of_them() -> None:
    """Dachy bez oceny sa nieznane, nie czyste — w mianowniku ich nie ma. Gdyby byly, wyszloby
    4/10 = 0,4 i kazdy obszar z kiepskim zdjeciem wygladalby na czystszy, niz jest."""
    stats = analysis_from_model(hand_counted_result(), hand_counted_facts()).stats

    assert stats.suspected_share == 0.5
    assert stats.suspected_share == round(stats.suspected / stats.analysed, 4)


def test_a_listed_building_without_a_score_is_not_counted_as_unsuspected() -> None:
    """Budynek 110 jest zgloszony i nie dostal oceny: „nie wiemy" nie znaczy „model nie widzi"."""
    stats = analysis_from_model(hand_counted_result(), hand_counted_facts()).stats

    listed_with_a_score = sum(1 for osm_id, _p, listed, _a in HAND_COUNTED if listed)
    assert stats.listed_not_suspected + stats.suspected_listed == listed_with_a_score


def test_the_threshold_boundary_counts_as_suspected() -> None:
    at_threshold = AreaModelResult(
        model_name=MODEL_ID,
        buildings=[ModelBuilding(osm_id=1, status="ok", probability=SUSPECTED_THRESHOLD, geometry=None)],
    )

    stats = analysis_from_model(at_threshold, facts_for(1)).stats

    assert (stats.suspected, stats.threshold) == (1, SUSPECTED_THRESHOLD)


def test_only_scored_buildings_reach_the_list() -> None:
    analysis = analysis_from_model(hand_counted_result(), hand_counted_facts())

    assert [building.id for building in analysis.buildings] == [101, 102, 107, 103, 104, 105, 106, 108]
    assert all(building.probability is not None for building in analysis.buildings)


def test_the_list_is_ordered_by_probability_and_then_by_identifier() -> None:
    """Remis rozstrzyga `osm_id`, zeby kolejnosc w panelu byla powtarzalna miedzy zapytaniami."""
    tie = AreaModelResult(
        model_name=MODEL_ID,
        buildings=[
            ModelBuilding(osm_id=222, status="ok", probability=0.6, geometry=None),
            ModelBuilding(osm_id=111, status="ok", probability=0.6, geometry=None),
            ModelBuilding(osm_id=333, status="ok", probability=0.9, geometry=None),
        ],
    )

    analysis = analysis_from_model(tie, facts_for(111, 222, 333))

    assert [building.id for building in analysis.buildings] == [333, 111, 222]


def test_an_empty_answer_from_the_model_is_zeros_not_an_error() -> None:
    analysis = analysis_from_model(AreaModelResult(model_name=MODEL_ID, buildings=[]), {})

    assert (analysis.stats.analysed, analysis.stats.no_result, analysis.stats.suspected) == (0, 0, 0)
    assert analysis.stats.suspected_share == 0.0  # dzielenie przez zero nie moze wywalic odpowiedzi
    assert analysis.stats.suspected_roof_area_m2 == 0.0
    assert analysis.stats.model_name == MODEL_ID
    assert analysis.buildings == []


def test_the_geometry_from_the_model_travels_unchanged() -> None:
    result = AreaModelResult(
        model_name=MODEL_ID,
        buildings=[ModelBuilding(osm_id=1, status="ok", probability=0.8, geometry=MULTIPOLYGON)],
    )

    analysis = analysis_from_model(result, facts_for(1))

    assert analysis.buildings[0].geometry == MULTIPOLYGON


def test_a_list_longer_than_the_limit_is_cut_and_admits_it() -> None:
    many = AreaModelResult(
        model_name=MODEL_ID,
        buildings=[ModelBuilding(osm_id=index, status="ok", probability=0.5, geometry=None) for index in range(1, 6)],
    )

    analysis = analysis_from_model(many, facts_for(1, 2, 3, 4, 5), limit=3)

    assert len(analysis.buildings) == 3
    assert analysis.truncated is True
    assert analysis.stats.analysed == 5  # statystyki obejmuja caly obszar, nie przycieta liste


# --- bramka limitow ---------------------------------------------------------------------------------


def test_the_gate_stays_silent_inside_the_limits() -> None:
    assert model_limit_problem(MODEL_MAX_AREA_KM2, MODEL_MAX_BUILDINGS) is None


def test_the_gate_quotes_the_area_and_both_limits() -> None:
    message = str(model_limit_problem(19.4))

    assert "19.4 km²" in message
    assert f"up to {MODEL_MAX_BUILDINGS} buildings" in message
    assert f"{format_km2(MODEL_MAX_AREA_KM2)} km²" in message
    assert "smaller rectangle" in message


def test_the_gate_quotes_the_number_of_buildings_with_a_thousands_separator() -> None:
    message = str(model_limit_problem(0.5, 1338))

    assert "1,338 buildings" in message
    assert "km²" in message  # limit powierzchni jest w komunikacie takze wtedy, gdy przebity jest inny


def test_the_gate_names_both_reasons_when_both_are_exceeded() -> None:
    message = str(model_limit_problem(19.4, 1338))

    assert "is 19.4 km²" in message
    assert "has 1,338 buildings" in message


def test_the_gate_is_stricter_than_the_registry_scan() -> None:
    """Skan rejestru przepuszcza 25 km2, model mniej — front musi czytac obie liczby."""
    assert MODEL_MAX_AREA_KM2 < MAX_AREA_KM2
    assert model_limit_problem(MODEL_MAX_AREA_KM2 + 0.1) is not None
    assert model_limit_problem(MODEL_MAX_AREA_KM2) is None


def test_the_gate_uses_the_limits_it_is_given_not_the_defaults() -> None:
    """Limity naleza do uruchomionej uslugi: lokalna kopia przyjmuje tyle, ile jej ustawimy,
    a wspoldzielona instancja miala 100 budynkow i 4 km2. Bramka musi isc za konfiguracja,
    inaczej blokuje zapytania, ktore by przeszly, albo wpuszcza te, ktore dostana cudze 413."""
    strict = model_limit_problem(5.0, 120, max_buildings=100, max_area_km2=4.0)

    assert strict is not None
    assert "up to 100 buildings and 4 km²" in strict
    assert "has 120 buildings" in strict
    # Te same liczby przy wyzszych limitach nie sa juz problemem.
    assert model_limit_problem(5.0, 120, max_buildings=500, max_area_km2=10.0) is None


# --- zapytania do bazy -------------------------------------------------------------------------------


async def test_the_facts_are_read_with_one_query_for_all_buildings() -> None:
    pool = FakePool(facts=[(101, 120.0, True), (102, 80.0, False)])

    facts = await read_building_facts(pool, [101, 102], timeout=1.0)

    assert len(pool.statements) == 1
    sql, params = pool.statements[0]
    assert "= ANY(%(ids)s)" in sql
    assert params == {"ids": ["101", "102"]}  # kolumna osm_id jest tekstowa (migracja 006)
    assert facts[101] == BuildingFacts(area_m2=120.0, listed=True)
    assert facts[102].listed is False


async def test_no_buildings_means_no_query_at_all() -> None:
    pool = FakePool()

    assert await read_building_facts(pool, [], timeout=1.0) == {}
    assert pool.statements == []


async def test_the_count_query_uses_the_same_bbox_operator_as_the_tiles() -> None:
    pool = FakePool(count=74)

    counted = await count_buildings(pool, selection(SMALL_SELECTION), timeout=1.0)

    assert counted == 74
    assert "geom && ST_MakeEnvelope" in " ".join(BUILDING_COUNT_SQL.split())
    assert pool.statements[0][1]["west"] == 21.5745


def test_the_listed_flag_comes_from_the_registry_column_and_nothing_else() -> None:
    sql = " ".join(BUILDING_FACTS_SQL.split())

    assert "(b.registry_matches > 0) AS listed" in sql
    assert "ST_Intersects" not in sql  # dopasowanie idzie po osm_id, nie geometrycznie


# --- caly endpoint ------------------------------------------------------------------------------------


def hand_counted_payload() -> dict[str, Any]:
    features = [feature(osm_id, probability) for osm_id, probability, _listed, _area in HAND_COUNTED]
    features += [feature(osm_id, None, status) for osm_id, status in NO_SCORE]
    return collection(*features)


def hand_counted_pool() -> FakePool:
    rows = [(osm_id, area, listed) for osm_id, _probability, listed, area in HAND_COUNTED]
    return FakePool(count=len(HAND_COUNTED) + len(NO_SCORE), facts=rows)


def test_the_endpoint_answers_with_statistics_buildings_and_the_model_name() -> None:
    seen, handle = responder(hand_counted_payload())

    with client_with(hand_counted_pool(), handle) as client:
        response = client.post(ANALYZE_PATH, json=SMALL_SELECTION)

    assert response.status_code == 200
    body = response.json()
    assert body["stats"] == {
        "analysed": 8,
        "noResult": 2,
        "suspected": 4,
        "suspectedShare": 0.5,
        "suspectedNotListed": 3,
        "suspectedListed": 1,
        "listedNotSuspected": 2,
        "suspectedRoofAreaM2": SUSPECTED_AREA_M2,
        "threshold": SUSPECTED_THRESHOLD,
        "modelName": MODEL_ID,
        # Oba zrodla ida z tego samego snapshotu OSM, wiec zero. Niezerowe znaczyloby, ze model
        # ocenil budynek, ktorego nie mamy — i wtedy nie wolno go liczyc jako „niezgloszony".
        "unknownToUs": 0,
    }
    assert body["truncated"] is False
    assert body["buildings"][0] == {
        "id": 101,
        "probability": 0.91,
        "listed": False,
        "areaM2": 120.0,
        "geometry": POLYGON,
    }
    # Caly prostokat idzie do modelu jednym zapytaniem, a do bazy ida dokladnie dwa: bramka i fakty.
    assert len(seen) == 1
    assert seen[0].url.path == "/v1/analyze"


def test_the_listed_flag_is_matched_by_osm_id_not_by_position() -> None:
    """Model oddaje budynki w swojej kolejnosci, a rejestr znamy tylko my — dopasowanie idzie
    po identyfikatorze, wiec przestawienie obiektow w odpowiedzi niczego nie przekreca."""
    payload = collection(feature(102, 0.80), feature(101, 0.91))
    pool = FakePool(count=2, facts=[(101, 120.0, False), (102, 200.5, True)])
    _seen, handle = responder(payload)

    with client_with(pool, handle) as client:
        body = client.post(ANALYZE_PATH, json=SMALL_SELECTION).json()

    listed = {building["id"]: building["listed"] for building in body["buildings"]}
    assert listed == {101: False, 102: True}
    facts_params = [params for sql, params in pool.statements if "ANY" in sql]
    assert facts_params == [{"ids": ["102", "101"]}]  # jedno zapytanie na caly obszar


def test_an_area_over_the_model_limit_is_refused_before_the_database_and_the_model() -> None:
    seen, handle = responder(hand_counted_payload())
    pool = FakePool(count=5000)
    expected = format_km2(bbox_area_km2(selection(HUGE_SELECTION)))

    with client_with(pool, handle) as client:
        response = client.post(ANALYZE_PATH, json=HUGE_SELECTION)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert f"is {expected} km²" in detail
    assert f"up to {MODEL_MAX_BUILDINGS} buildings" in detail
    assert pool.statements == []  # za duzy prostokat nie kosztuje ani zapytania do bazy
    assert seen == []  # ani jednego z dziesieciu zapytan na minute, ktore ma tamta instancja


def test_too_many_buildings_is_refused_with_the_counted_number() -> None:
    seen, handle = responder(hand_counted_payload())
    pool = FakePool(count=1338)

    with client_with(pool, handle) as client:
        response = client.post(ANALYZE_PATH, json=SMALL_SELECTION)

    assert response.status_code == 400
    assert "has 1,338 buildings" in response.json()["detail"]
    assert len(pool.statements) == 1  # tylko bramka; faktow juz nie czytamy
    assert seen == []  # lepiej powiedziec to od razu niz czekac na cudze 413


def test_a_dead_model_is_a_503_not_a_500_and_not_a_pretend_result() -> None:
    def explode(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with client_with(hand_counted_pool(), explode) as client:
        response = client.post(ANALYZE_PATH, json=SMALL_SELECTION)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "no result is not the same as zero" in detail.lower()
    assert affirmative_claims(detail) == []


def test_a_busy_model_says_when_to_come_back() -> None:
    _seen, handle = responder({"detail": {"code": "BUSY"}}, status_code=429, headers={"Retry-After": "30"})

    with client_with(hand_counted_pool(), handle) as client:
        response = client.post(ANALYZE_PATH, json=SMALL_SELECTION)

    assert response.status_code == 503
    assert "30" in response.json()["detail"]


def test_a_refused_request_is_a_503_with_the_status_code() -> None:
    """Gdyby nasza bramka kiedys rozminela sie z limitem tamtej instancji, uzytkownik ma zobaczyc
    odmowe, a nie polowe danych podana jako komplet."""
    _seen, handle = responder({"detail": {"code": "TOO_MANY_BUILDINGS"}}, status_code=413)

    with client_with(hand_counted_pool(), handle) as client:
        response = client.post(ANALYZE_PATH, json=SMALL_SELECTION)

    assert response.status_code == 503
    assert "413" in response.json()["detail"]


def test_an_answer_without_a_model_name_is_refused_instead_of_shown() -> None:
    _seen, handle = responder(collection(feature(101, 0.9), model_id=None))

    with client_with(hand_counted_pool(), handle) as client:
        response = client.post(ANALYZE_PATH, json=SMALL_SELECTION)

    assert response.status_code == 503
    assert "which model" in response.json()["detail"]


def test_an_empty_answer_from_the_model_is_a_200_with_zeros() -> None:
    _seen, handle = responder(collection())

    with client_with(FakePool(count=0), handle) as client:
        response = client.post(ANALYZE_PATH, json=SMALL_SELECTION)

    assert response.status_code == 200
    body = response.json()
    assert body["buildings"] == []
    assert body["stats"]["analysed"] == 0
    assert body["stats"]["suspectedShare"] == 0.0
    assert body["stats"]["modelName"] == MODEL_ID


def test_the_mock_provider_does_not_get_to_produce_area_statistics() -> None:
    """Bez modelu endpoint mowi „nie wiemy". Szesc licznikow policzonych ze skrotow
    identyfikatorow wygladaloby jak pomiar, a nie jak demo."""
    with client_with(hand_counted_pool()) as client:  # bez podstawionego dostawcy: zostaje atrapa
        response = client.post(ANALYZE_PATH, json=SMALL_SELECTION)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "not connected" in detail
    assert affirmative_claims(detail) == []


def test_a_dead_database_is_a_503() -> None:
    _seen, handle = responder(hand_counted_payload())

    with client_with(FakePool(error=OSError("connection refused")), handle) as client:
        response = client.post(ANALYZE_PATH, json=SMALL_SELECTION)

    assert response.status_code == 503
    assert response.json()["detail"] == "The database is not responding."


def test_inverted_corners_are_rejected_before_anything_else() -> None:
    seen, handle = responder(hand_counted_payload())
    pool = FakePool(count=10)
    inverted = {"sw": {"lng": 21.578, "lat": 51.358}, "ne": {"lng": 21.5745, "lat": 51.3555}}

    with client_with(pool, handle) as client:
        response = client.post(ANALYZE_PATH, json=inverted)

    assert response.status_code == 400
    assert "north corner" in response.json()["detail"]
    assert (pool.statements, seen) == ([], [])


def test_the_limits_endpoint_publishes_the_model_limits_next_to_the_old_one() -> None:
    """Stare pole zostaje nietkniete — front, ktory czyta tylko je, dalej dziala."""
    with client_with(FakePool()) as client:
        response = client.get("/api/area/limits")

    assert response.status_code == 200
    assert response.json() == {
        "maxAreaKm2": MAX_AREA_KM2,
        "model": {"maxBuildings": MODEL_MAX_BUILDINGS, "maxAreaKm2": MODEL_MAX_AREA_KM2},
    }


def test_the_corner_order_is_the_one_the_model_api_expects() -> None:
    assert corners(selection(SMALL_SELECTION)) == (21.5745, 51.3555, 21.578, 51.358)


@pytest.mark.parametrize("status", ["low_quality", "imagery_error", "geometry_error", ""])
def test_no_status_other_than_ok_is_ever_counted_as_a_clear_roof(status: str) -> None:
    result = AreaModelResult(
        model_name=MODEL_ID,
        buildings=[ModelBuilding(osm_id=1, status=status, probability=None, geometry=None)],
    )

    stats = analysis_from_model(result, {}).stats

    assert (stats.analysed, stats.no_result, stats.suspected) == (0, 1, 0)


def test_a_building_our_database_does_not_know_is_not_counted_as_unreported() -> None:
    """Najwazniejsza liczba aplikacji nie moze dac sie zawyzyc rozjazdem snapshotow.

    Wczesniej taki budynek dostawal `listed=False` i ladowal w `suspected_not_listed`, czyli
    w zestawieniu „nikt tego nie zglosil, a model cos widzi". To bylo twierdzenie bez pokrycia:
    o budynku, ktorego nie ma w naszej bazie, nie wiemy nic — takze tego, czy ktos go zglosil.
    """
    result = AreaModelResult(
        buildings=[
            ModelBuilding(osm_id=1, status="ok", probability=0.9, geometry=None),
            ModelBuilding(osm_id=2, status="ok", probability=0.8, geometry=None),
        ],
        model_name=MODEL_ID,
    )
    # Baza zna tylko pierwszy budynek; drugi jest dla nas nieznany.
    facts = {1: BuildingFacts(area_m2=100.0, listed=False)}

    analysis = analysis_from_model(result, facts)

    assert analysis.stats.unknown_to_us == 1
    assert analysis.stats.analysed == 1  # nieznany nie jest „oceniony przez nas"
    assert analysis.stats.suspected == 1
    assert analysis.stats.suspected_not_listed == 1  # tylko ten, o ktorym naprawde wiemy
    assert [building.id for building in analysis.buildings] == [1]


def test_unknown_buildings_stay_out_of_every_counter() -> None:
    result = AreaModelResult(
        buildings=[ModelBuilding(osm_id=9, status="ok", probability=0.95, geometry=None)],
        model_name=MODEL_ID,
    )

    analysis = analysis_from_model(result, {})

    stats = analysis.stats
    assert stats.unknown_to_us == 1
    assert (stats.analysed, stats.suspected, stats.suspected_not_listed, stats.suspected_listed) == (0, 0, 0, 0)
    assert stats.suspected_roof_area_m2 == 0.0
    assert stats.suspected_share == 0.0
    assert analysis.buildings == []
