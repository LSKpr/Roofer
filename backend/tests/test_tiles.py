from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.tiles import POINT_MIN_ZOOM, POINT_TILE, POLYGON_MIN_ZOOM, POLYGON_TILE, tile_sql, within_grid
from tests.conftest import FakePool

SETTINGS = Settings(database_url="postgresql://unused")


def client_with(pool: FakePool) -> TestClient:
    return TestClient(create_app(SETTINGS, pool_factory=lambda _settings: pool))


def test_close_zoom_serves_building_outlines() -> None:
    assert tile_sql(POLYGON_MIN_ZOOM) is POLYGON_TILE


def test_middle_zoom_serves_only_centroids_of_listed_buildings() -> None:
    assert tile_sql(POLYGON_MIN_ZOOM - 1) is POINT_TILE
    assert tile_sql(POINT_MIN_ZOOM) is POINT_TILE


def test_far_zoom_serves_nothing() -> None:
    assert tile_sql(POINT_MIN_ZOOM - 1) is None


def test_grid_rejects_coordinates_outside_the_zoom_level() -> None:
    assert within_grid(1, 1, 1)
    assert not within_grid(1, 2, 0)
    assert not within_grid(1, 0, -1)


def test_tile_endpoint_returns_the_vector_tile_with_a_cache_header() -> None:
    with client_with(FakePool(row=(b"tile-bytes",))) as client:
        response = client.get(f"/api/tiles/buildings/{POLYGON_MIN_ZOOM}/9000/5500.mvt")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert response.headers["cache-control"] == "public, max-age=3600"
    assert response.content == b"tile-bytes"


def test_empty_tile_is_204_instead_of_an_empty_200() -> None:
    with client_with(FakePool(row=(b"",))) as client:
        response = client.get(f"/api/tiles/buildings/{POLYGON_MIN_ZOOM}/9000/5500.mvt")

    assert response.status_code == 204


def test_zoom_below_the_threshold_does_not_touch_the_database() -> None:
    pool = FakePool(row=(b"tile-bytes",))

    with client_with(pool) as client:
        response = client.get("/api/tiles/buildings/3/1/1.mvt")

    assert response.status_code == 204
    assert pool.timeouts == []


def test_coordinates_outside_the_grid_are_rejected() -> None:
    with client_with(FakePool(row=(b"tile-bytes",))) as client:
        response = client.get("/api/tiles/buildings/2/9/0.mvt")

    assert response.status_code == 400


def test_a_dead_database_degrades_to_503_instead_of_breaking_the_map() -> None:
    with client_with(FakePool(error=OSError("connection refused"))) as client:
        response = client.get(f"/api/tiles/buildings/{POLYGON_MIN_ZOOM}/9000/5500.mvt")

    assert response.status_code == 503
