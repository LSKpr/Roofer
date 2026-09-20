"""Dostawca HTTP oceny pokrycia dachu, bez sieci.

Ksztalt zadania i odpowiedzi jest przepisany z dokumentacji autora API i sprawdzony na zywo przez
tunel SSH: zapytanie o prostokat budynku 27469148 oddalo dwa obiekty (nasz blok i garaz sasiada),
oba z `source_id` rownym naszemu `osm_id`, oraz `meta.model_id`. Dlatego testy trzymaja sie tego
konkretnego ksztaltu, a nie wyobrazenia o nim.
"""

import asyncio
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.prediction import (
    ANALYZE_PATH,
    SUSPECTED_THRESHOLD,
    BuildingShape,
    HttpModelProvider,
    UnavailableProvider,
    analysis_from_properties,
    analyze_request,
    build_provider,
    find_feature,
)
from tests.test_prediction import affirmative_claims

TOKEN = "sekretny-token-ktory-nie-ma-prawa-wyciec"
MODEL_ID = "70b702e1922493f0b57be82240f651ea2509f6bc2e35bdf0048017bcfe93d67c"
OSM_ID = 27469148

BUILDING = BuildingShape(
    id=OSM_ID,
    lng=21.1001,
    lat=52.2396,
    west=21.1000423,
    south=52.2396121,
    east=21.1002977,
    north=52.2397557,
    area_m2=163.0,
)


def feature(source_id: int | str, status: str = "ok", probability: float | None = 0.72, **extra: Any) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": []},
        "properties": {"source_id": str(source_id), "status": status, "asbestos_probability": probability, **extra},
    }


def collection(*features: dict, model_id: str | None = MODEL_ID) -> dict:
    return {"type": "FeatureCollection", "features": list(features), "meta": {"model_id": model_id, "matched": 1}}


def provider_with(handler: Any, **kwargs: Any) -> HttpModelProvider:
    """Dostawca gadajacy z atrapa transportu; zegar jest wstrzykiwany, wiec testy nie spia."""
    return HttpModelProvider(
        base_url="http://model.example",
        token=TOKEN,
        transport=httpx.MockTransport(handler),
        min_interval_s=kwargs.pop("min_interval_s", 0.0),
        clock=kwargs.pop("clock", lambda: 1000.0),
        **kwargs,
    )


def responder(payload: dict, status_code: int = 200, headers: dict[str, str] | None = None):
    """Atrapa, ktora zapisuje kazde zadanie — po to, zeby sprawdzic naglowek i cialo."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code, json=payload, headers=headers or {})

    return seen, handle


def test_request_body_has_the_corners_the_model_api_expects() -> None:
    # Kolejnosc i nazwy pol sa kontraktem: zamiana longitude z latitude daje wynik, ktory wyglada
    # poprawnie i dotyczy innego miejsca w Polsce.
    assert analyze_request(BUILDING) == {
        "south_west": {"longitude": 21.1000423, "latitude": 52.2396121},
        "north_east": {"longitude": 21.1002977, "latitude": 52.2397557},
    }


def test_our_building_is_found_by_source_id_among_the_neighbours() -> None:
    """W prostokacie jednego budynku siedza tez sasiednie dachy — na zywo obok bloku wyszedl garaz.

    Dlatego dopasowujemy po `source_id`, a nie bierzemy pierwszego obiektu z listy.
    """
    payload = collection(feature(381012561, probability=0.16), feature(OSM_ID, probability=0.24))

    found = find_feature(payload, OSM_ID)

    assert found is not None
    assert found["source_id"] == str(OSM_ID)
    assert found["asbestos_probability"] == 0.24


def test_internal_identifiers_are_not_used_for_matching() -> None:
    # `building_id` i `id` sa kluczami ich lokalnej bazy; zgodnosc z naszym osm_id byloby przypadkiem.
    payload = collection(feature(999, building_id=f"osm:{OSM_ID}"))

    assert find_feature(payload, OSM_ID) is None


def test_a_scored_roof_becomes_a_model_verdict_with_the_model_name() -> None:
    above = analysis_from_properties(feature(OSM_ID, probability=0.72)["properties"], MODEL_ID)
    below = analysis_from_properties(feature(OSM_ID, probability=0.24)["properties"], MODEL_ID)

    assert (above.source, above.verdict, above.probability) == ("model", "suspected", 0.72)
    assert (below.source, below.verdict, below.probability) == ("model", "unlikely", 0.24)
    assert above.model_name == MODEL_ID


def test_the_threshold_is_the_one_shared_with_the_mock() -> None:
    # Jeden prog dla atrapy i dla modelu, zeby werdykt nie zmienial znaczenia po podmianie dostawcy.
    at_threshold = analysis_from_properties(feature(OSM_ID, probability=SUSPECTED_THRESHOLD)["properties"], MODEL_ID)

    assert at_threshold.verdict == "suspected"


@pytest.mark.parametrize("status", ["low_quality", "imagery_error", "geometry_error"])
def test_every_non_ok_status_is_an_honest_unknown(status: str) -> None:
    """Te trzy statusy to powod, dla ktorego ten model w ogole dalo sie podlaczyc uczciwie:
    autor rozroznia „sprawdzilem i nie widze" od „nie sprawdzilem"."""
    analysis = analysis_from_properties(feature(OSM_ID, status=status, probability=None)["properties"], MODEL_ID)

    assert (analysis.source, analysis.verdict, analysis.probability) == ("model", "unknown", None)
    assert analysis.model_name == MODEL_ID


def test_low_quality_repeats_the_reasons_given_by_the_service() -> None:
    properties = feature(OSM_ID, status="low_quality", probability=None, reasons=["low_sharpness", "few_edges"])[
        "properties"
    ]

    analysis = analysis_from_properties(properties, MODEL_ID)

    assert "low_sharpness" in analysis.note
    assert "few_edges" in analysis.note


def test_a_result_without_a_model_name_is_not_passed_off_as_a_model_result() -> None:
    # `RoofAnalysis` wymaga nazwy przy source="model"; wymyslenie jej byloby podaniem atrapy za model.
    analysis = analysis_from_properties(feature(OSM_ID)["properties"], None)

    assert (analysis.source, analysis.verdict, analysis.probability) == ("unavailable", "unknown", None)


def test_every_note_says_the_model_looked_at_a_different_photo_than_the_card_shows() -> None:
    """Karta pokazuje ortofotomape GUGiK, a model patrzy na Google Satellite. Bez tego zdania
    ktos porownalby ocene ze zdjeciem obok i wyciagnal wniosek z dwoch roznych zrodel."""
    scored = analysis_from_properties(feature(OSM_ID)["properties"], MODEL_ID)
    unknown = analysis_from_properties(feature(OSM_ID, status="low_quality", probability=None)["properties"], MODEL_ID)

    for analysis in (scored, unknown):
        assert "Google" in analysis.note
        assert "GUGiK" in analysis.note
        assert affirmative_claims(analysis.note) == []


async def test_the_bearer_token_travels_in_the_header_and_nowhere_else() -> None:
    seen, handle = responder(collection(feature(OSM_ID)))
    provider = provider_with(handle)

    analysis = await provider.analyze(BUILDING)
    await provider.close()

    request = seen[0]
    assert request.url.path == ANALYZE_PATH
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in analysis.note
    assert TOKEN not in repr(provider)  # token nie ma prawa trafic do logu ani do tracebacku


async def test_the_second_question_about_the_same_building_does_not_reach_the_network() -> None:
    """Limit tamtej instancji to 10 zapytan na minute, a karta pyta przy kazdym kliknieciu."""
    seen, handle = responder(collection(feature(OSM_ID)))
    provider = provider_with(handle)

    first = await provider.analyze(BUILDING)
    second = await provider.analyze(BUILDING)
    await provider.close()

    assert first == second
    assert len(seen) == 1


async def test_an_expired_cache_entry_is_asked_again() -> None:
    now = {"value": 1000.0}
    seen, handle = responder(collection(feature(OSM_ID)))
    provider = provider_with(handle, cache_ttl_s=60.0, clock=lambda: now["value"])

    await provider.analyze(BUILDING)
    now["value"] += 61.0
    await provider.analyze(BUILDING)
    await provider.close()

    assert len(seen) == 2


@pytest.mark.parametrize("status_code", [401, 413, 422, 500, 504])
async def test_every_http_error_is_an_unknown_instead_of_an_exception(status_code: int) -> None:
    _seen, handle = responder({"detail": {"code": "BOOM"}}, status_code=status_code)
    provider = provider_with(handle)

    analysis = await provider.analyze(BUILDING)
    await provider.close()

    assert (analysis.source, analysis.verdict, analysis.probability) == ("unavailable", "unknown", None)


async def test_a_busy_service_says_when_to_come_back() -> None:
    _seen, handle = responder({"detail": {"code": "BUSY"}}, status_code=429, headers={"Retry-After": "30"})
    provider = provider_with(handle)

    analysis = await provider.analyze(BUILDING)
    await provider.close()

    assert analysis.verdict == "unknown"
    assert "30" in analysis.note


async def test_a_dead_service_does_not_take_the_building_card_down() -> None:
    def explode(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = provider_with(explode)

    analysis = await provider.analyze(BUILDING)
    await provider.close()

    assert (analysis.source, analysis.verdict) == ("unavailable", "unknown")


async def test_a_building_missing_from_the_answer_is_not_an_error() -> None:
    _seen, handle = responder(collection(feature(381012561)))
    provider = provider_with(handle)

    analysis = await provider.analyze(BUILDING)
    await provider.close()

    assert (analysis.source, analysis.verdict, analysis.probability) == ("unavailable", "unknown", None)
    assert affirmative_claims(analysis.note) == []


async def test_a_broken_json_is_an_unknown_too() -> None:
    def broken(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>nie json</html>")

    provider = provider_with(broken)

    analysis = await provider.analyze(BUILDING)
    await provider.close()

    assert analysis.verdict == "unknown"


async def test_requests_are_serialised_because_the_service_takes_one_at_a_time() -> None:
    running = {"now": 0, "max": 0}

    async def slow(_request: httpx.Request) -> httpx.Response:
        running["now"] += 1
        running["max"] = max(running["max"], running["now"])
        await asyncio.sleep(0)
        running["now"] -= 1
        return httpx.Response(200, json=collection(feature(OSM_ID)))

    provider = provider_with(slow)
    other = BuildingShape(id=381012561, lng=21.1, lat=52.2, west=21.1, south=52.2, east=21.11, north=52.21)

    await asyncio.gather(provider.analyze(BUILDING), provider.analyze(other))
    await provider.close()

    assert running["max"] == 1


def settings_for(url: str = "", token: str = "") -> Settings:
    """Ustawienia z jawnymi wartosciami: bez tego `Settings` doczyta prawdziwy `.env` i test
    sprawdzalby konfiguracje tej maszyny zamiast zachowania kodu."""
    return Settings(
        database_url="postgresql://unused",
        prediction_provider="model",
        prediction_api_url=url,
        prediction_api_token=token,
    )


def test_a_model_provider_without_a_url_or_a_token_degrades_to_unknown() -> None:
    """Zla konfiguracja nie moze pokazac zadnego wyniku — tak samo jak jej brak."""
    assert isinstance(build_provider("model", settings_for()), UnavailableProvider)
    assert isinstance(build_provider("model", settings_for(url="http://x")), UnavailableProvider)
    assert isinstance(build_provider("model", settings_for(token="t")), UnavailableProvider)


def test_the_token_is_not_printed_when_settings_land_in_a_traceback() -> None:
    """Pydantic wypisuje cale Settings w komunikacie bledu — zwykly napis wyciekal do tracebacku.

    Zlapal to inny test, ktory sprawdzal co innego: w jego wydruku stal caly token z .env.
    """
    settings = settings_for(url="http://model.example", token=TOKEN)

    assert TOKEN not in repr(settings)
    assert TOKEN not in str(settings)
    assert TOKEN not in str(settings.model_dump())
    # Wartosc jest dostepna tylko jawnie, wiec przypadkowy log jej nie zabierze.
    assert settings.prediction_api_token.get_secret_value() == TOKEN


def test_a_fully_configured_model_provider_is_the_http_one() -> None:
    settings = Settings(
        database_url="postgresql://unused",
        prediction_provider="model",
        prediction_api_url="http://127.0.0.1:8010/",
        prediction_api_token=TOKEN,
    )

    provider = build_provider("model", settings)

    assert isinstance(provider, HttpModelProvider)
    assert provider.base_url == "http://127.0.0.1:8010"  # bez konczacego ukosnika, zeby nie bylo //v1
    assert TOKEN not in repr(provider)
