"""Ocena pokrycia dachu bez bazy i bez sieci: geometrie budynku podaje FakePool, a dostawce
wybiera konfiguracja. Wiekszosc testow dotyka funkcji wprost, bo caly sens tego modulu to reguly
uczciwosci wyniku (atrapa oznaczona jako atrapa, brak wyniku jako null, zero tylko dla oceny 0).
"""

from dataclasses import fields
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.prediction import (
    BUILDING_SHAPE_SQL,
    MOCK_SUSPECTED_NOTE,
    MOCK_UNKNOWN_NOTE,
    MOCK_UNLIKELY_NOTE,
    MODEL_BUSY_NOTE,
    MODEL_IMAGERY_NOTE,
    MODEL_MISSING_NOTE,
    MODEL_NO_RESULT_NOTE,
    PROVIDER_ERROR_NOTE,
    STATUS_NOTES,
    SUSPECTED_THRESHOLD,
    UNAVAILABLE_NOTE,
    BuildingShape,
    MockProvider,
    RoofAnalysis,
    RoofAnalysisProvider,
    UnavailableProvider,
    build_provider,
    mock_analysis,
    shape_from_row,
    stable_unit,
)
from app.routes import prediction as prediction_routes
from tests.conftest import FakePool

ANALYSIS_PATH = "/api/buildings/{osm_id}/analysis"

# Identyfikatorem budynku jest `osm_id`, wiec wszystkie liczby tutaj sa prawdziwymi osm_id
# zgloszonych budynkow z bazy. Wybrane tak, zeby pokryly wszystkie trzy werdykty atrapy (policzone
# raz i przepisane tutaj — gdyby ktos zmienil sol albo prog, te testy maja krzyczec).
SUSPECTED_ID = 28287777
UNLIKELY_ID = 27469148
UNKNOWN_ID = 31002632

SAMPLE_IDS = (
    27469148,
    28287777,
    28759017,
    28965947,
    30683417,
    31002632,
    31060079,
    31968370,
    42905974,
    70540123,
    88999259,
    93883385,
)

# Identyfikatory, dla ktorych atrapa oddaje liczbe — tylko takie moga sie roznic probability
# (budynki bez wyniku maja `None` i to jest w porzadku, ze maja je wszystkie takie samo).
GRADED_IDS = (27469148, 28287777, 28759017, 28965947, 30683417, 31060079, 31968370, 93883385)

# Kolejnosc kolumn BUILDING_SHAPE_SQL: id, area_m2, lng, lat, west, south, east, north.
ROW = (SUSPECTED_ID, 126.6, 21.0800, 51.2500, 21.0797, 51.2498, 21.0803, 51.2502)

# Slowa, ktorych wynik oceny nie ma prawa uzyc twierdzaco. Model patrzy na wyglad pokrycia,
# a nie na sklad materialu, wiec „detected asbestos" czy „this roof is safe" to nadinterpretacja.
# Noty sa po angielsku (taki jest interfejs), wiec straznik slownictwa tez jest angielski.
FORBIDDEN_CLAIMS = ("detected asbestos", "asbestos-free", "no asbestos", "safe", "clean")
NEGATIONS = ("not ", "never ", "no result", "nothing")
SENTENCE_BREAKS = ".!?;"

# Zdanie, ktore musi padnac w kazdej nocie stanu „nie wiemy" — inaczej brak wyniku da sie przeczytac
# jako ocene zero, czyli „sprawdzone i nic nie widac".
NO_RESULT_PHRASE = "no result is not the same as zero"


def settings_with(provider: str = "mock") -> Settings:
    return Settings(database_url="postgresql://unused", prediction_provider=provider)


def client_with(pool: FakePool, provider: str = "mock") -> TestClient:
    """Router oceny podlacza main.py; dopoki tego nie zrobi, test montuje go sam."""
    app = create_app(settings_with(provider), pool_factory=lambda _settings: pool)
    if ANALYSIS_PATH not in {getattr(route, "path", None) for route in app.routes}:
        app.include_router(prediction_routes.router, prefix="/api")
    return TestClient(app)


def shape(building_id: int = SUSPECTED_ID) -> BuildingShape:
    return BuildingShape(
        id=building_id,
        lng=21.08,
        lat=51.25,
        west=21.0797,
        south=51.2498,
        east=21.0803,
        north=51.2502,
        area_m2=126.6,
    )


def sentences(text: str) -> list[str]:
    """Podzial na zdania, bo przeczenie („does not mean that...") czesto stoi przed przecinkiem."""
    parts = [text]
    for mark in SENTENCE_BREAKS:
        parts = [piece for part in parts for piece in part.split(mark)]
    return [part for part in parts if part.strip()]


def affirmative_claims(note: str) -> list[str]:
    """Zakazane sformulowania uzyte TWIERDZACO w podanej nocie.

    Zdanie negujace jest dopuszczalne („a low score does not mean the roof is safe"), wiec slowo
    liczy sie tylko wtedy, gdy w jego zdaniu nie ma przeczenia. Regula patrzy na cale zdanie, wiec
    da sie ja oszukac zdaniem, ktore neguje zupelnie co innego — dlatego obok jest drugi test,
    ktory wymaga, zeby nasze noty tych slow w ogole nie uzywaly.
    """
    lowered = note.lower()
    used: list[str] = []
    for sentence in sentences(lowered):
        negated = any(negation in sentence for negation in NEGATIONS)
        if negated:
            continue
        used.extend(claim for claim in FORBIDDEN_CLAIMS if claim in sentence)
    return used


def all_notes() -> dict[str, str]:
    """Kazda nota, ktora moze trafic do karty budynku: atrapa, brak dostawcy i prawdziwy model."""
    return {
        "mock/suspected": MOCK_SUSPECTED_NOTE,
        "mock/unlikely": MOCK_UNLIKELY_NOTE,
        "mock/unknown": MOCK_UNKNOWN_NOTE,
        "unavailable": UNAVAILABLE_NOTE,
        "provider-error": PROVIDER_ERROR_NOTE,
        "model/scored": MODEL_IMAGERY_NOTE,
        "model/no-result": MODEL_NO_RESULT_NOTE.format(powod=STATUS_NOTES["low_quality"]) + " " + MODEL_IMAGERY_NOTE,
        "model/missing": MODEL_MISSING_NOTE,
        "model/busy": MODEL_BUSY_NOTE.format(seconds="30"),
    }


# Noty stanow „nie wiemy". Kazda z nich musi powiedziec wprost, ze wyniku nie ma i ze to nie to
# samo co ocena zero; noty z liczba (mock/suspected, mock/unlikely, model/scored) tego nie musza.
NO_RESULT_NOTES = (
    "mock/unknown",
    "unavailable",
    "provider-error",
    "model/no-result",
    "model/missing",
    "model/busy",
)


def one_line(sql: str) -> str:
    """SQL bez wyrownania kolumn, zeby asercje nie pilnowaly liczby spacji."""
    return " ".join(sql.split())


def test_the_provider_query_addresses_the_building_by_osm_id() -> None:
    """Wejsciem skrotu jest identyfikator budynku, a od teraz jest nim `osm_id`.

    To jest ulepszenie, nie tylko spojnosc z reszta API: `osm_id` przezywa ponowny import, wiec
    werdykt atrapy dla tego samego dachu przestaje sie zmieniac. Przy kluczu z sekwencji ten sam
    budynek dostawal po imporcie nowy numer (2 585 326 - 5 170 544 po drugim przebiegu), a wiec
    nowa „ocene" — na demo wygladalo to jak losowanie.
    """
    sql = one_line(BUILDING_SHAPE_SQL)

    assert "b.osm_id::bigint AS id" in sql
    assert "WHERE b.osm_id = %(id)s::text" in sql  # rzutowanie parametru, zeby dzialal indeks
    assert "b.id" not in sql  # klucz z sekwencji nie wchodzi juz do atrapy


def test_stable_unit_lands_inside_the_unit_interval_and_never_moves() -> None:
    first = [stable_unit(building_id, "sol:") for building_id in SAMPLE_IDS]
    second = [stable_unit(building_id, "sol:") for building_id in SAMPLE_IDS]

    assert first == second  # ten sam identyfikator to ta sama liczba, bez ziarna i bez losowania
    assert all(0.0 <= value < 1.0 for value in first)
    assert len(set(first)) == len(SAMPLE_IDS)


def test_stable_unit_with_another_salt_is_an_independent_draw() -> None:
    # Dwie sole daja dwie niezalezne liczby z jednego identyfikatora: „jaka ocena" i „czy jest".
    assert stable_unit(SUSPECTED_ID, "a:") != stable_unit(SUSPECTED_ID, "b:")


def test_shape_from_row_reads_the_bbox_in_sw_then_ne_order() -> None:
    built = shape_from_row(ROW)

    assert built is not None
    assert (built.id, built.area_m2) == (SUSPECTED_ID, 126.6)
    assert (built.lng, built.lat) == (21.08, 51.25)
    assert built.bbox == (21.0797, 51.2498, 21.0803, 51.2502)


def test_shape_from_a_missing_row_is_none_not_an_error() -> None:
    assert shape_from_row(None) is None


def test_provider_sql_never_looks_at_the_registry() -> None:
    """Atrapa nie ma prawa zgadywac na podstawie zgloszenia — to byloby przepisanie rejestru."""
    lowered = BUILDING_SHAPE_SQL.lower()

    for forbidden in ("registry_matches", "registry_records", "building_registry_match", "nr_dzialki"):
        assert forbidden not in lowered
    assert "osm_buildings" in lowered
    assert "st_xmin" in lowered  # dostawca dostaje bbox, bo przyszle API modelu pyta prostokatem


def test_provider_input_carries_nothing_from_the_registry() -> None:
    """Gdyby ktos chcial „poprawic" atrape rejestrem, musi najpierw zmienic ten test."""
    names = {field.name for field in fields(BuildingShape)}

    assert names == {"id", "lng", "lat", "west", "south", "east", "north", "area_m2"}


async def test_mock_answers_the_same_building_identically_every_time() -> None:
    provider = MockProvider()

    for building_id in SAMPLE_IDS:
        first = await provider.analyze(shape(building_id))
        second = await MockProvider().analyze(shape(building_id))
        assert first == second  # demo nie moze migac przy kazdym kliknieciu


async def test_mock_answers_different_buildings_differently() -> None:
    results = [await MockProvider().analyze(shape(building_id)) for building_id in GRADED_IDS]

    assert len({result.probability for result in results}) == len(GRADED_IDS)
    assert {result.verdict for result in results} == {"suspected", "unlikely"}


async def test_mock_looks_only_at_the_identifier() -> None:
    """Powierzchnia i polozenie nie moga wplywac na atrape — inaczej wyglada jak prawdziwa ocena."""
    elsewhere = BuildingShape(
        id=SUSPECTED_ID, lng=14.5, lat=54.0, west=14.4, south=53.9, east=14.6, north=54.1, area_m2=9999.0
    )

    assert await MockProvider().analyze(shape(SUSPECTED_ID)) == await MockProvider().analyze(elsewhere)


def test_mock_is_recognisable_as_a_mock_without_reading_the_ui() -> None:
    for building_id in SAMPLE_IDS:
        result = mock_analysis(building_id)
        assert result.source == "mock"
        assert result.model_name is None
        assert "Demonstration result" in result.note
        assert "no ML model" in result.note


def test_mock_verdict_and_probability_always_agree() -> None:
    for building_id in range(1, 200):
        result = mock_analysis(building_id)
        if result.verdict == "unknown":
            assert result.probability is None  # brak wyniku to null, nigdy 0.0
        else:
            assert result.probability is not None
            assert 0.0 <= result.probability <= 1.0
            expected = "suspected" if result.probability >= SUSPECTED_THRESHOLD else "unlikely"
            assert result.verdict == expected


def test_mock_shows_all_three_states_including_no_result() -> None:
    verdicts = {mock_analysis(building_id).verdict for building_id in range(1, 60)}

    assert verdicts == {"suspected", "unlikely", "unknown"}
    assert mock_analysis(SUSPECTED_ID).verdict == "suspected"
    assert mock_analysis(UNLIKELY_ID).verdict == "unlikely"
    assert mock_analysis(UNKNOWN_ID).verdict == "unknown"


async def test_unavailable_provider_admits_it_has_nothing() -> None:
    result = await UnavailableProvider().analyze(shape())

    assert (result.source, result.verdict, result.probability, result.model_name) == (
        "unavailable",
        "unknown",
        None,
        None,
    )


async def test_configuration_none_selects_the_unavailable_provider() -> None:
    provider = build_provider("none")
    result = await provider.analyze(shape())

    assert isinstance(provider, UnavailableProvider)
    assert (result.source, result.verdict, result.probability) == ("unavailable", "unknown", None)


def test_configuration_mock_selects_the_mock_provider() -> None:
    assert isinstance(build_provider("mock"), MockProvider)
    assert isinstance(build_provider("  MOCK  "), MockProvider)


def test_an_unknown_provider_name_degrades_to_unavailable_instead_of_inventing_a_result() -> None:
    assert isinstance(build_provider("zewnetrzne-api"), UnavailableProvider)
    assert isinstance(build_provider(""), UnavailableProvider)


def test_both_providers_fit_the_socket() -> None:
    assert isinstance(MockProvider(), RoofAnalysisProvider)
    assert isinstance(UnavailableProvider(), RoofAnalysisProvider)


def test_a_missing_result_may_not_be_written_as_zero() -> None:
    with pytest.raises(ValueError, match="None"):
        RoofAnalysis(source="mock", verdict="unknown", probability=0.0, model_name=None, note="x")
    with pytest.raises(ValueError, match="None"):
        RoofAnalysis(source="unavailable", verdict="unknown", probability=0.0, model_name=None, note="x")


def test_a_verdict_with_a_number_needs_a_number_in_range() -> None:
    with pytest.raises(ValueError, match="0-1"):
        RoofAnalysis(source="mock", verdict="suspected", probability=None, model_name=None, note="x")
    with pytest.raises(ValueError, match="0-1"):
        RoofAnalysis(source="mock", verdict="unlikely", probability=1.5, model_name=None, note="x")


def test_a_mock_may_not_present_itself_as_a_model() -> None:
    with pytest.raises(ValueError, match="Atrapa"):
        RoofAnalysis(source="mock", verdict="suspected", probability=0.7, model_name="eternit-v1", note="x")


def test_a_model_result_must_name_the_model() -> None:
    with pytest.raises(ValueError, match="model"):
        RoofAnalysis(source="model", verdict="suspected", probability=0.7, model_name=None, note="x")

    named = RoofAnalysis(source="model", verdict="suspected", probability=0.7, model_name="eternit-v1", note="x")
    assert named.model_name == "eternit-v1"


def test_no_result_from_a_missing_provider_must_stay_unknown() -> None:
    with pytest.raises(ValueError, match="unknown"):
        RoofAnalysis(source="unavailable", verdict="suspected", probability=0.7, model_name=None, note="x")


def test_the_vocabulary_rule_tells_a_claim_from_a_denial() -> None:
    """Straznik slownictwa po angielsku: liczy sie zdanie, nie samo slowo."""
    assert affirmative_claims("This roof is safe.") == ["safe"]
    assert affirmative_claims("The model detected asbestos on this roof.") == ["detected asbestos"]
    assert affirmative_claims("This roof is clean.") == ["clean"]
    assert affirmative_claims("This building is asbestos-free.") == ["asbestos-free"]
    assert affirmative_claims("A low score does not mean the roof is safe.") == []
    assert affirmative_claims("We never say that the model detected asbestos.") == []
    assert affirmative_claims("No result is not the same as zero.") == []
    # Regula patrzy na zdanie, wiec twierdzenie w pierwszym zdaniu wychodzi mimo przeczenia w drugim.
    assert affirmative_claims("This roof is clean. Nothing was found here.") == ["clean"]


def test_no_note_claims_anything_about_asbestos_itself() -> None:
    for label, note in all_notes().items():
        assert affirmative_claims(note) == [], label
        # Drugie zabezpieczenie: nasze noty w ogole nie uzywaja tych slow, wiec regula nie musi
        # rozstrzygac watpliwych zdan.
        for claim in FORBIDDEN_CLAIMS:
            assert claim not in note.lower(), f"{label}: {claim}"


def test_notes_explain_what_the_model_actually_recognises() -> None:
    """Pokrycie, a nie sklad materialu — i nie potwierdzenie azbestu."""
    assert "cement-asbestos" in MOCK_SUSPECTED_NOTE
    assert "the look of the covering, not the material" in MOCK_SUSPECTED_NOTE
    assert "not the presence of asbestos" in MOCK_SUSPECTED_NOTE
    assert "cement-asbestos" in MOCK_UNLIKELY_NOTE
    assert "the look of the covering, not the material" in MODEL_IMAGERY_NOTE
    assert "77% accuracy and 63% asbestos recall" in MODEL_IMAGERY_NOTE
    assert NO_RESULT_PHRASE in MOCK_UNKNOWN_NOTE.lower()
    assert NO_RESULT_PHRASE in UNAVAILABLE_NOTE.lower()


def test_every_note_is_readable_and_admits_when_there_is_no_result() -> None:
    """To, co naprawde musi przezyc kazde tlumaczenie noty.

    Nastepca testu, ktory wymagal polskich ogonkow: po przejsciu interfejsu na angielski pilnowal
    juz tylko jezyka, a nie sensu. Liczy sie, ze nota w ogole jest, ze stan „nie wiemy" mowi wprost
    o braku wyniku (bo inaczej czyta sie go jak ocene zero) i ze zadna nota nie twierdzi niczego
    o samym azbescie.
    """
    notes = all_notes()

    for label, note in notes.items():
        assert note.strip(), label
        assert affirmative_claims(note) == [], label

    for label in NO_RESULT_NOTES:
        assert NO_RESULT_PHRASE in notes[label].lower(), label


def test_the_note_of_a_scored_roof_points_at_the_imagery_the_model_actually_saw() -> None:
    """Karta pokazuje ortofotomape GUGiK, a model patrzyl na Google Satellite — to dwa zrodla."""
    assert "Google Satellite (zoom 20), not the GUGiK aerial imagery shown in this card" in MODEL_IMAGERY_NOTE


def test_endpoint_returns_the_full_contract_in_camel_case() -> None:
    with client_with(FakePool(row=ROW)) as client:
        response = client.get(f"/api/buildings/{SUSPECTED_ID}/analysis")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"source", "verdict", "probability", "modelName", "note"}
    assert body["source"] == "mock"
    assert body["modelName"] is None
    assert body["verdict"] == "suspected"
    assert body["probability"] == mock_analysis(SUSPECTED_ID).probability
    assert body["note"] == MOCK_SUSPECTED_NOTE


def test_endpoint_answers_identically_when_asked_twice() -> None:
    with client_with(FakePool(row=ROW)) as client:
        first = client.get(f"/api/buildings/{SUSPECTED_ID}/analysis")
        second = client.get(f"/api/buildings/{SUSPECTED_ID}/analysis")

    assert first.json() == second.json()


def test_endpoint_reports_no_result_as_null_not_zero() -> None:
    row = (UNKNOWN_ID, *ROW[1:])

    with client_with(FakePool(row=row)) as client:
        body = client.get(f"/api/buildings/{UNKNOWN_ID}/analysis").json()

    assert body["verdict"] == "unknown"
    assert body["probability"] is None
    assert body["note"] == MOCK_UNKNOWN_NOTE


def test_endpoint_with_the_none_provider_says_it_has_no_model() -> None:
    with client_with(FakePool(row=ROW), provider="none") as client:
        response = client.get(f"/api/buildings/{SUSPECTED_ID}/analysis")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "source": "unavailable",
        "verdict": "unknown",
        "probability": None,
        "modelName": None,
        "note": UNAVAILABLE_NOTE,
    }


def test_a_missing_building_is_404_with_a_message_for_the_user() -> None:
    with client_with(FakePool(row=None)) as client:
        response = client.get("/api/buildings/999999999/analysis")

    assert response.status_code == 404
    assert response.json()["detail"] == "There is no building with this identifier."


def test_a_dead_database_degrades_to_503_instead_of_a_traceback() -> None:
    with client_with(FakePool(error=OSError("connection refused"))) as client:
        response = client.get(f"/api/buildings/{SUSPECTED_ID}/analysis")

    assert response.status_code == 503
    assert response.json()["detail"] == "The database is not responding."


def test_a_broken_provider_answers_unknown_instead_of_breaking_the_building_card() -> None:
    """Padniete zewnetrzne zrodlo ma stan „nieznany", a nie 500 i nie zmyslona liczba."""

    class BrokenProvider:
        source = "model"

        async def analyze(self, building: Any) -> RoofAnalysis:
            raise OSError("serwis modelu nie odpowiada")

    with client_with(FakePool(row=ROW)) as client:
        client.app.state.roof_provider = BrokenProvider()
        response = client.get(f"/api/buildings/{SUSPECTED_ID}/analysis")

    assert response.status_code == 200
    body = response.json()
    assert (body["source"], body["verdict"], body["probability"]) == ("unavailable", "unknown", None)
    assert body["note"] == PROVIDER_ERROR_NOTE


def test_the_database_read_uses_the_configured_timeout() -> None:
    pool = FakePool(row=ROW)

    with client_with(pool) as client:
        client.get(f"/api/buildings/{SUSPECTED_ID}/analysis")

    assert pool.timeouts == [settings_with().database_timeout_s]
