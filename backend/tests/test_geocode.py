"""Wyszukiwanie miejsc bez sieci: Nominatima udaje httpx.MockTransport, a ogranicznik 1/s
sprawdzamy jako czysta funkcje i na sztucznym zegarze, wiec zaden test nie spi naprawde."""

from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.geocode import (
    Geocoder,
    RateLimitedError,
    RateLimiter,
    UpstreamError,
    clamp_limit,
    normalize_query,
    search_params,
    slot_delay,
    to_bbox,
    to_place,
    to_places,
)
from app.main import create_app
from app.routes import geocode as geocode_routes
from tests.conftest import FakePool

SETTINGS = Settings(database_url="postgresql://unused")

# Fragment prawdziwej odpowiedzi Nominatima (format=jsonv2) na fraze „zwolen". Wspolrzedne
# i boundingbox przychodza jako STRINGI, a boundingbox jest w kolejnosci [south, north, west, east].
NOMINATIM_JSON = [
    {
        "place_id": 297582132,
        "licence": "Data (c) OpenStreetMap contributors, ODbL 1.0. http://osm.org/copyright",
        "osm_type": "relation",
        "osm_id": 2758076,
        "lat": "51.3610283",
        "lon": "21.5904618",
        "category": "boundary",
        "type": "administrative",
        "place_rank": 16,
        "importance": 0.43,
        "addresstype": "town",
        "name": "Zwolen",
        "display_name": "Zwolen, gmina Zwolen, powiat zwolenski, wojewodztwo mazowieckie, 26-700, Polska",
        "boundingbox": ["51.3400000", "51.3900000", "21.5500000", "21.6300000"],
    },
    {
        "place_id": 297404441,
        "osm_type": "relation",
        "osm_id": 2758075,
        "lat": "51.3456789",
        "lon": "21.6012345",
        "category": "boundary",
        "type": "administrative",
        "addresstype": "municipality",
        "name": "gmina Zwolen",
        "display_name": "gmina Zwolen, powiat zwolenski, wojewodztwo mazowieckie, Polska",
        "boundingbox": ["51.2700000", "51.4300000", "21.4700000", "21.7300000"],
    },
]


async def no_sleep(seconds: float) -> None:
    """Ogranicznik ma podjac decyzje, a nie zatrzymac testu."""


def frozen_limiter(min_interval_s: float = 0.0) -> RateLimiter:
    return RateLimiter(min_interval_s=min_interval_s, clock=lambda: 100.0, sleep=no_sleep)


def client_with(handler: Callable[[httpx.Request], httpx.Response], limiter: RateLimiter | None = None) -> TestClient:
    """Router geokodowania podlacza main.py; dopoki tego nie zrobi, test montuje go sam."""
    app = create_app(SETTINGS, pool_factory=lambda _settings: FakePool())
    if "/api/geocode" not in {getattr(route, "path", None) for route in app.routes}:
        app.include_router(geocode_routes.router, prefix="/api")
    app.state.geocoder = Geocoder(
        user_agent=SETTINGS.nominatim_user_agent,
        url=SETTINGS.nominatim_url,
        transport=httpx.MockTransport(handler),
        limiter=limiter or frozen_limiter(),
    )
    return TestClient(app)


def serving(payload: object, calls: list[httpx.Request] | None = None) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, json=payload)

    return handler


def test_normalize_query_trims_collapses_and_lowercases() -> None:
    assert normalize_query("  Zwolen   MAZOWIECKIE ") == "zwolen mazowieckie"
    assert normalize_query("   ") == ""


def test_clamp_limit_keeps_the_request_inside_our_range() -> None:
    assert (clamp_limit(0), clamp_limit(5), clamp_limit(50)) == (1, 5, 10)


def test_search_params_ask_nominatim_only_about_poland() -> None:
    assert search_params("zwolen", 5) == {"format": "jsonv2", "countrycodes": "pl", "limit": "5", "q": "zwolen"}


def test_bounding_box_is_reordered_from_nominatim_to_south_west_north_east() -> None:
    # Nominatim: [south, north, west, east]; my: [south, west, north, east].
    assert to_bbox(["51.34", "51.39", "21.55", "21.63"]) == [51.34, 21.55, 51.39, 21.63]


def test_a_missing_or_broken_bounding_box_becomes_null() -> None:
    assert to_bbox(None) is None
    assert to_bbox(["51.34", "51.39"]) is None
    assert to_bbox(["poludnie", "51.39", "21.55", "21.63"]) is None


def test_nominatim_entry_is_mapped_to_our_model() -> None:
    place = to_place(NOMINATIM_JSON[0])

    assert place == {
        "label": "Zwolen, gmina Zwolen, powiat zwolenski, wojewodztwo mazowieckie, 26-700, Polska",
        "lat": 51.3610283,
        "lng": 21.5904618,
        "bbox": [51.34, 21.55, 51.39, 21.63],
        "kind": "town",
    }


def test_an_entry_without_coordinates_is_skipped_instead_of_breaking_the_list() -> None:
    broken = {"display_name": "Bez wspolrzednych, Polska", "boundingbox": None}

    assert to_place(broken) is None
    assert len(to_places([NOMINATIM_JSON[0], broken, "nie slownik"])) == 1


def test_a_payload_that_is_not_a_list_is_treated_as_an_outage() -> None:
    with pytest.raises(UpstreamError):
        to_places({"error": "Unable to geocode"})


def test_slot_delay_spaces_requests_one_second_apart() -> None:
    assert slot_delay(None, now_s=100.0) == 0.0  # pierwsze zapytanie idzie od razu
    assert slot_delay(101.0, now_s=100.0) == 1.0
    assert slot_delay(101.0, now_s=101.5) == 0.0  # okno juz minelo


async def test_rate_limiter_queues_three_requests_and_refuses_the_fourth() -> None:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    limiter = RateLimiter(min_interval_s=1.0, max_wait_s=2.0, clock=lambda: 100.0, sleep=sleep)

    assert await limiter.acquire() == 0.0
    assert await limiter.acquire() == 1.0
    assert await limiter.acquire() == 2.0
    with pytest.raises(RateLimitedError):
        await limiter.acquire()  # czekanie 3 s to juz nie kolejka, tylko wiszace zadanie
    assert slept == [1.0, 2.0]


def test_search_returns_places_in_camel_case() -> None:
    with client_with(serving(NOMINATIM_JSON)) as client:
        response = client.get("/api/geocode", params={"q": "Zwolen"})

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 2
    assert results[0]["label"].startswith("Zwolen,")
    assert results[0]["bbox"] == [51.34, 21.55, 51.39, 21.63]
    assert results[0]["kind"] == "town"
    assert (results[0]["lat"], results[0]["lng"]) == (51.3610283, 21.5904618)


def test_request_carries_a_user_agent_that_identifies_the_application() -> None:
    calls: list[httpx.Request] = []

    with client_with(serving(NOMINATIM_JSON, calls)) as client:
        client.get("/api/geocode", params={"q": "Zwolen", "limit": 3})

    assert len(calls) == 1
    assert "Roofer" in calls[0].headers["user-agent"]
    assert calls[0].url.params["countrycodes"] == "pl"
    assert calls[0].url.params["limit"] == "3"


def test_a_repeated_search_is_served_from_the_cache_without_touching_the_network() -> None:
    calls: list[httpx.Request] = []

    with client_with(serving(NOMINATIM_JSON, calls)) as client:
        first = client.get("/api/geocode", params={"q": "Zwolen"})
        second = client.get("/api/geocode", params={"q": "  zwolen "})

    assert first.json() == second.json()
    assert len(calls) == 1  # znormalizowana fraza trafila w cache


def test_an_empty_query_is_rejected_before_any_request() -> None:
    calls: list[httpx.Request] = []

    with client_with(serving(NOMINATIM_JSON, calls)) as client:
        response = client.get("/api/geocode", params={"q": "   "})

    assert response.status_code == 400
    assert "miejscowosci" in response.json()["detail"]
    assert calls == []


def test_a_timeout_degrades_to_503_with_a_polish_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("zbyt dlugo", request=request)

    with client_with(handler) as client:
        response = client.get("/api/geocode", params={"q": "Zwolen"})

    assert response.status_code == 503
    assert "Nominatim" in response.json()["detail"]


def test_an_html_error_page_degrades_to_503() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>Bandwidth limit exceeded</body></html>")

    with client_with(handler) as client:
        response = client.get("/api/geocode", params={"q": "Zwolen"})

    assert response.status_code == 503


def test_a_server_error_from_nominatim_degrades_to_503() -> None:
    with client_with(lambda request: httpx.Response(502, text="bad gateway")) as client:
        response = client.get("/api/geocode", params={"q": "Zwolen"})

    assert response.status_code == 503


def test_a_second_search_within_the_same_second_answers_429() -> None:
    calls: list[httpx.Request] = []
    # Zegar stoi, a odstep to 10 s, wiec drugie zapytanie musialoby czekac dluzej niz max_wait_s.
    limiter = RateLimiter(min_interval_s=10.0, max_wait_s=2.0, clock=lambda: 100.0, sleep=no_sleep)

    with client_with(serving(NOMINATIM_JSON, calls), limiter=limiter) as client:
        first = client.get("/api/geocode", params={"q": "Zwolen"})
        second = client.get("/api/geocode", params={"q": "Radom"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert "chwile" in second.json()["detail"]
    assert len(calls) == 1
