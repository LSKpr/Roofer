"""Proxy ortofoto bez sieci i bez bazy: transport httpx jest podstawiony, pula to FakePool."""

import asyncio
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.imagery import (
    ORIGIN_SHIFT_M,
    PNG_MAGIC,
    ImageryClient,
    TileCache,
    getmap_params,
    looks_like_png,
    square_bbox,
    tile_bbox,
)
from app.main import create_app
from app.routes import imagery as imagery_routes
from tests.conftest import FakePool

SETTINGS = Settings(database_url="postgresql://unused")
PNG = PNG_MAGIC + b"udawany obraz"
SERVICE_EXCEPTION = b'<?xml version="1.0"?><ServiceExceptionReport><ServiceException code="LayerNotDefined"/>'
TILE_PATH = "/api/imagery/orthophoto/18/146372/86317.png"
ROOF_PATH = "/api/buildings/7/roof.png"
TILE_TEMPLATE = "/api/imagery/orthophoto/{z}/{x}/{y}.png"


def png_response(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)


def wired(app: FastAPI) -> bool:
    """Czy main.py juz podlaczyl router ortofoto.

    FastAPI 0.141 pakuje `include_router` w obiekt `_IncludedRouter`, wiec ani `app.routes`, ani
    `app.url_path_for` nie widza sciezek podrouterow — jedynym publicznym spisem jest OpenAPI.
    Cache schematu zerujemy, bo zaraz mozemy dopisac trasy.
    """
    paths = app.openapi()["paths"]
    app.openapi_schema = None
    return TILE_TEMPLATE in paths


def app_with(
    handler: Callable[[httpx.Request], httpx.Response],
    pool: FakePool | None = None,
    max_parallel: int = 4,
) -> FastAPI:
    app = create_app(SETTINGS, pool_factory=lambda _settings: pool or FakePool())
    # Podlaczamy sami tylko dopoki main.py tego nie robi — inaczej byly by dwie kopie tras.
    if not wired(app):
        app.include_router(imagery_routes.router, prefix="/api")
    app.state.imagery = ImageryClient(
        base_url="https://wms.test/orto",
        layer="Raster",
        max_parallel=max_parallel,
        transport=httpx.MockTransport(handler),
    )
    return app


def recording_handler(response: Callable[[httpx.Request], httpx.Response]) -> tuple[list[httpx.Request], Callable]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response(request)

    return seen, handler


def test_tile_bbox_at_zoom_zero_covers_the_whole_world() -> None:
    assert tile_bbox(0, 0, 0) == (-ORIGIN_SHIFT_M, -ORIGIN_SHIFT_M, ORIGIN_SHIFT_M, ORIGIN_SHIFT_M)


def test_tile_bbox_counts_rows_from_the_north() -> None:
    assert tile_bbox(1, 1, 0) == (0.0, 0.0, ORIGIN_SHIFT_M, ORIGIN_SHIFT_M)
    assert tile_bbox(1, 0, 1) == (-ORIGIN_SHIFT_M, -ORIGIN_SHIFT_M, 0.0, 0.0)


def test_roof_bbox_is_square_and_keeps_the_centre() -> None:
    result = square_bbox((1000.0, 2000.0, 1020.0, 2010.0), margin=0.2)

    width = result[2] - result[0]
    height = result[3] - result[1]
    assert width == pytest.approx(height)
    assert width == pytest.approx(24.0)  # dluzszy bok 20 m plus 20% marginesu
    assert (result[0] + result[2]) / 2 == pytest.approx(1010.0)
    assert (result[1] + result[3]) / 2 == pytest.approx(2005.0)


def test_tiny_building_gets_a_minimum_frame() -> None:
    result = square_bbox((0.0, 0.0, 2.0, 2.0))

    assert result[2] - result[0] == pytest.approx(12.0)


def test_getmap_uses_wms_130_in_web_mercator() -> None:
    params = getmap_params((1.0, 2.0, 3.0, 4.0), 256, 256, "Raster")

    assert params["VERSION"] == "1.3.0"
    assert params["CRS"] == "EPSG:3857"
    assert params["LAYERS"] == "Raster"
    assert params["STYLES"] == ""
    assert params["BBOX"] == "1.000,2.000,3.000,4.000"
    assert params["WIDTH"] == "256"
    # Bez tego kafel poza zasiegiem nalotu przychodzi bialy i zakrywa podklad OSM.
    assert params["TRANSPARENT"] == "TRUE"


def test_only_a_real_png_counts_as_an_image() -> None:
    assert looks_like_png("image/png", PNG)
    assert not looks_like_png("text/xml", SERVICE_EXCEPTION)
    assert not looks_like_png("image/png", SERVICE_EXCEPTION)  # naglowek potrafi klamac
    assert not looks_like_png(None, PNG)


def test_cache_drops_the_least_recently_used_entry() -> None:
    cache = TileCache(max_entries=2, max_bytes=1024)
    cache.put(("Raster", 1, 1, 1), b"a")
    cache.put(("Raster", 1, 1, 2), b"b")
    cache.get(("Raster", 1, 1, 1))  # odswieza pierwszy wpis
    cache.put(("Raster", 1, 1, 3), b"c")

    assert cache.get(("Raster", 1, 1, 1)) == b"a"
    assert cache.get(("Raster", 1, 1, 2)) is None
    assert len(cache) == 2


def test_cache_respects_the_byte_budget() -> None:
    cache = TileCache(max_entries=100, max_bytes=10)
    cache.put(("Raster", 1, 0, 0), b"x" * 6)
    cache.put(("Raster", 1, 0, 1), b"y" * 6)

    assert cache.get(("Raster", 1, 0, 0)) is None
    assert cache.total_bytes == 6
    cache.put(("Raster", 1, 0, 2), b"z" * 11)  # wpis wiekszy od calego budzetu odrzucamy
    assert cache.total_bytes == 6


def test_settings_drive_the_client() -> None:
    client = ImageryClient.from_settings(SETTINGS)

    assert client.base_url == SETTINGS.imagery_wms_url
    assert client.layer == "Raster"
    assert client.max_parallel == 4
    assert client.cache.max_bytes == SETTINGS.imagery_cache_mb * 1024 * 1024


def test_tile_endpoint_returns_png_with_a_day_of_cache() -> None:
    with TestClient(app_with(png_response)) as client:
        response = client.get(TILE_PATH)

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert response.content == PNG


def test_service_exception_with_status_200_is_treated_as_a_failure() -> None:
    def xml(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/xml"}, content=SERVICE_EXCEPTION)

    with TestClient(app_with(xml)) as client:
        response = client.get(TILE_PATH)

    assert response.status_code == 503
    assert response.content == b""


def test_timeout_degrades_to_503() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("za dlugo", request=request)

    with TestClient(app_with(timeout)) as client:
        response = client.get(TILE_PATH)

    assert response.status_code == 503


def test_server_error_from_gugik_degrades_to_503() -> None:
    with TestClient(app_with(lambda _request: httpx.Response(500, text="awaria"))) as client:
        response = client.get(TILE_PATH)

    assert response.status_code == 503


def test_tile_outside_the_grid_is_rejected_without_touching_the_network() -> None:
    seen, handler = recording_handler(png_response)

    with TestClient(app_with(handler)) as client:
        response = client.get("/api/imagery/orthophoto/2/9/0.png")

    assert response.status_code == 400
    assert seen == []


def test_second_request_for_the_same_tile_is_served_from_cache() -> None:
    seen, handler = recording_handler(png_response)

    with TestClient(app_with(handler)) as client:
        first = client.get(TILE_PATH)
        second = client.get(TILE_PATH)

    assert (first.status_code, second.status_code) == (200, 200)
    assert second.content == PNG
    assert len(seen) == 1


def test_roof_crop_asks_for_a_square_frame_around_the_building() -> None:
    seen, handler = recording_handler(png_response)
    pool = FakePool(row=(1000.0, 2000.0, 1020.0, 2010.0))

    with TestClient(app_with(handler, pool=pool)) as client:
        response = client.get(ROOF_PATH)

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(seen) == 1
    params = seen[0].url.params
    assert params["BBOX"] == "998.000,1993.000,1022.000,2017.000"
    assert (params["WIDTH"], params["HEIGHT"]) == ("384", "384")


def test_roof_crop_size_can_be_chosen_within_limits() -> None:
    seen, handler = recording_handler(png_response)
    pool = FakePool(row=(1000.0, 2000.0, 1020.0, 2010.0))

    with TestClient(app_with(handler, pool=pool)) as client:
        response = client.get(ROOF_PATH, params={"size": 512})

    assert response.status_code == 200
    assert seen[0].url.params["WIDTH"] == "512"


@pytest.mark.parametrize("size", [64, 2048])
def test_roof_crop_rejects_sizes_outside_the_range(size: int) -> None:
    seen, handler = recording_handler(png_response)
    pool = FakePool(row=(1000.0, 2000.0, 1020.0, 2010.0))

    with TestClient(app_with(handler, pool=pool)) as client:
        response = client.get(ROOF_PATH, params={"size": size})

    assert response.status_code == 422
    assert seen == []


def test_unknown_building_has_no_roof_image() -> None:
    with TestClient(app_with(png_response, pool=FakePool(row=None))) as client:
        response = client.get(ROOF_PATH)

    assert response.status_code == 404
    assert response.json()["detail"] == "Nie ma budynku o tym identyfikatorze."


def test_dead_database_does_not_break_the_roof_image() -> None:
    with TestClient(app_with(png_response, pool=FakePool(error=OSError("connection refused")))) as client:
        response = client.get(ROOF_PATH)

    assert response.status_code == 503


class CountingTransport(httpx.AsyncBaseTransport):
    """Transport, ktory pamieta najwieksza liczbe zapytan obecnych naraz."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)


async def test_parallel_requests_to_gugik_are_capped() -> None:
    transport = CountingTransport()
    client = ImageryClient("https://wms.test/orto", "Raster", max_parallel=2, transport=transport)

    await asyncio.gather(*(client.tile(18, 146372, 86300 + offset) for offset in range(8)))
    await client.aclose()

    assert transport.peak == 2


async def test_the_http_client_is_created_once_and_shared() -> None:
    client = ImageryClient("https://wms.test/orto", "Raster", transport=httpx.MockTransport(png_response))

    first, second = await asyncio.gather(client._http(), client._http())
    await client.aclose()

    assert first is second
