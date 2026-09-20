"""Skan obszaru bez bazy: kazde zapytanie dostaje przygotowany wiersz z FakePool."""

from fastapi.testclient import TestClient

from app.area import (
    AREA_SCAN_SQL,
    MAX_AREA_KM2,
    BoundingBox,
    area_problem,
    bbox_area_km2,
    bbox_problem,
    format_km2,
    scan_from_row,
    scan_parameters,
)
from app.config import Settings
from app.main import create_app
from app.routes import area as area_routes
from tests.conftest import FakePool

SETTINGS = Settings(database_url="postgresql://unused")

# Kolejnosc kolumn AREA_SCAN_SQL: total, listed, dachy, dachy zgloszone, rejestr, lista budynkow.
# Ostatnia kolumna to json, wiec psycopg oddaje ja jako gotowa liste slownikow.
#
# `id` na liscie to osm_id — dlatego liczby sa z zakresu identyfikatorow OSM, a nie z sekwencji bazy.
ROW = (
    12,
    5,
    2500.5,
    900.25,
    7,
    [
        {"id": 27469148, "areaM2": 300.0, "lng": 21.08, "lat": 51.25, "nrDzialki": "146501_1.1.1"},
        {"id": 28287777, "areaM2": 120.5, "lng": 21.081, "lat": 51.251, "nrDzialki": None},
    ],
)

# Prostokat ~1 x 1 km w okolicy Zwolenia.
SMALL_SELECTION = {"sw": {"lat": 51.250, "lng": 21.0750}, "ne": {"lat": 51.259, "lng": 21.0893}}
# Prostokat ~0,05 x 0,15 stopnia, czyli kilkadziesiat km2 — powyzej limitu.
HUGE_SELECTION = {"sw": {"lat": 51.250, "lng": 21.000}, "ne": {"lat": 51.300, "lng": 21.150}}


def client_with(pool: FakePool) -> TestClient:
    """Router obszaru podlacza main.py; dopoki tego nie zrobi, test montuje go sam."""
    app = create_app(SETTINGS, pool_factory=lambda _settings: pool)
    if "/api/area/scan" not in {getattr(route, "path", None) for route in app.routes}:
        app.include_router(area_routes.router, prefix="/api")
    return TestClient(app)


def selection(payload: dict[str, dict[str, float]]) -> BoundingBox:
    return BoundingBox(
        south=payload["sw"]["lat"],
        west=payload["sw"]["lng"],
        north=payload["ne"]["lat"],
        east=payload["ne"]["lng"],
    )


def test_bbox_area_of_a_two_kilometre_square_is_four_square_kilometres() -> None:
    # 0,018 stopnia szerokosci to ~2 km, a 0,0287 stopnia dlugosci na 51,25 N to tez ~2 km.
    area = bbox_area_km2(BoundingBox(south=51.245, west=21.0750, north=51.263, east=21.1037))

    assert 3.9 < area < 4.1


def test_bbox_area_of_the_same_span_shrinks_towards_the_pole() -> None:
    near_equator = bbox_area_km2(BoundingBox(south=0.0, west=0.0, north=0.1, east=0.1))
    far_north = bbox_area_km2(BoundingBox(south=60.0, west=0.0, north=60.1, east=0.1))

    assert far_north < near_equator / 1.9  # cos(60 stopni) = 0,5


def test_bbox_area_of_a_degenerate_selection_is_zero() -> None:
    assert bbox_area_km2(BoundingBox(south=51.25, west=21.08, north=51.25, east=21.08)) == 0.0


def test_bbox_problem_names_the_inverted_corner() -> None:
    inverted_latitude = BoundingBox(south=51.30, west=21.00, north=51.25, east=21.10)
    inverted_longitude = BoundingBox(south=51.25, west=21.10, north=51.30, east=21.00)

    assert "polnoc" in str(bbox_problem(inverted_latitude))
    assert "wschod" in str(bbox_problem(inverted_longitude))
    assert bbox_problem(BoundingBox(south=51.25, west=21.00, north=51.30, east=21.10)) is None


def test_bbox_problem_rejects_coordinates_outside_the_globe() -> None:
    assert "Szerokosc" in str(bbox_problem(BoundingBox(south=-91.0, west=21.0, north=51.3, east=21.1)))
    assert "Dlugosc" in str(bbox_problem(BoundingBox(south=51.2, west=21.0, north=51.3, east=181.0)))


def test_area_problem_quotes_both_numbers_and_stays_silent_below_the_limit() -> None:
    message = str(area_problem(41.2))

    assert "41,2" in message
    assert "25" in message
    assert area_problem(MAX_AREA_KM2) is None


def test_format_km2_uses_a_polish_decimal_comma_and_drops_a_trailing_zero() -> None:
    assert format_km2(41.234) == "41,2"
    assert format_km2(25.0) == "25"


def one_line(sql: str) -> str:
    """SQL bez wyrownania kolumn, zeby asercje nie pilnowaly liczby spacji."""
    return " ".join(sql.split())


def test_the_listed_building_identifier_is_osm_id_as_an_integer() -> None:
    """Ksztalt odpowiedzi jest bez zmian, zmienilo sie znaczenie `id`: to osm_id, ten sam adres,
    ktory niesie kafel i ktorym wola sie /api/buildings/{id}. Rzutowanie na bigint jest potrzebne,
    bo kolumna jest tekstowa, a `id` w kontrakcie to liczba."""
    sql = one_line(AREA_SCAN_SQL)

    assert "b.osm_id::bigint AS id" in sql
    assert "'id', listed.id" in sql
    # Wewnetrzny klucz zostaje w zlaczeniu z dopasowaniami i nigdzie wiecej.
    assert sql.count("= b.id") == 1
    assert "m.building_id = b.id" in sql


def test_the_listed_order_does_not_depend_on_the_sequence_key() -> None:
    """Tie-breaker po osm_id, bo klucz z sekwencji po ponownym imporcie przestawialby kolejnosc
    budynkow o rownej powierzchni — a lista idzie do panelu i do CSV."""
    sql = one_line(AREA_SCAN_SQL)

    assert "ORDER BY b.area_m2 DESC, id" in sql
    assert "ORDER BY b.area_m2 DESC, b.id" not in sql


def test_parameters_ask_for_one_building_more_than_we_return() -> None:
    parameters = scan_parameters(selection(SMALL_SELECTION), limit=500)

    assert parameters["limit"] == 501
    assert parameters["south"] == 51.250


def test_scan_from_row_counts_not_listed_buildings_and_their_share() -> None:
    scan = scan_from_row(ROW, area_km2=1.0)

    assert (scan.stats.total, scan.stats.listed, scan.stats.not_listed) == (12, 5, 7)
    assert scan.stats.listed_share == round(5 / 12, 4)
    assert scan.truncated is False


def test_scan_from_row_cuts_the_list_and_admits_it() -> None:
    row = (3, 3, 10.0, 10.0, 3, [{"id": index} for index in range(3)])

    scan = scan_from_row(row, area_km2=1.0, limit=2)

    assert len(scan.listed_buildings) == 2
    assert scan.truncated is True


def test_scan_from_row_of_an_empty_area_is_zeros_not_an_error() -> None:
    scan = scan_from_row(None, area_km2=1.0)

    assert (scan.stats.total, scan.stats.listed_share, scan.stats.registry_records) == (0, 0.0, 0)
    assert scan.listed_buildings == []


def test_scan_returns_statistics_and_the_listed_buildings() -> None:
    with client_with(FakePool(row=ROW)) as client:
        response = client.post("/api/area/scan", json=SMALL_SELECTION)

    assert response.status_code == 200
    body = response.json()
    assert body["stats"] == {
        "total": 12,
        "listed": 5,
        "notListed": 7,
        "listedShare": round(5 / 12, 4),
        "roofAreaM2": 2500.5,
        "listedRoofAreaM2": 900.25,
        "registryRecords": 7,
    }
    assert body["truncated"] is False
    assert 0.9 < body["areaKm2"] < 1.1
    assert body["listedBuildings"][0] == {
        "id": 27469148,  # osm_id, czyli adres, ktorym front zapyta o karte budynku
        "areaM2": 300.0,
        "centroid": {"lng": 21.08, "lat": 51.25},
        "nrDzialki": "146501_1.1.1",
    }
    assert body["listedBuildings"][1]["nrDzialki"] is None


def test_empty_area_answers_with_zeros() -> None:
    with client_with(FakePool(row=None)) as client:
        response = client.post("/api/area/scan", json=SMALL_SELECTION)

    assert response.status_code == 200
    assert response.json()["stats"]["total"] == 0


def test_inverted_corners_are_rejected_without_touching_the_database() -> None:
    pool = FakePool(row=ROW)
    inverted = {"sw": {"lat": 51.259, "lng": 21.0893}, "ne": {"lat": 51.250, "lng": 21.0750}}

    with client_with(pool) as client:
        response = client.post("/api/area/scan", json=inverted)

    assert response.status_code == 400
    assert "polnoc" in response.json()["detail"]
    assert pool.timeouts == []


def test_a_selection_over_the_limit_is_rejected_with_both_numbers() -> None:
    pool = FakePool(row=ROW)
    expected = format_km2(bbox_area_km2(selection(HUGE_SELECTION)))

    with client_with(pool) as client:
        response = client.post("/api/area/scan", json=HUGE_SELECTION)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert expected in detail
    assert format_km2(MAX_AREA_KM2) in detail
    assert pool.timeouts == []  # za duzy obszar nie kosztuje bazy ani jednego zapytania


def test_coordinates_outside_the_globe_are_rejected() -> None:
    with client_with(FakePool(row=ROW)) as client:
        response = client.post(
            "/api/area/scan", json={"sw": {"lat": 51.25, "lng": 21.0}, "ne": {"lat": 200.0, "lng": 21.1}}
        )

    assert response.status_code == 422  # zakres pilnuje pydantic, wiec FastAPI oddaje 422


def test_limits_endpoint_publishes_the_same_constant_that_guards_the_scan() -> None:
    with client_with(FakePool(row=ROW)) as client:
        response = client.get("/api/area/limits")

    assert response.status_code == 200
    assert response.json() == {"maxAreaKm2": MAX_AREA_KM2}


def test_a_dead_database_degrades_to_503() -> None:
    with client_with(FakePool(error=OSError("connection refused"))) as client:
        response = client.post("/api/area/scan", json=SMALL_SELECTION)

    assert response.status_code == 503
    assert response.json()["detail"] == "Baza nie odpowiada."
