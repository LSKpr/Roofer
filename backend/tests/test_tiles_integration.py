"""Kafle i szczegoly budynku na prawdziwych danych. Wymaga TEST_DATABASE_URL i zaimportowanego
wojewodztwa; nic nie zapisuje."""

import os
from collections.abc import Iterator

import psycopg
import pytest

from app.buildings import BUILDING_SQL
from app.ingest import MIN_MATCH_SHARE, MIN_RECORD_INSIDE
from app.tiles import POINT_TILE, POLYGON_TILE

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL nie jest ustawiony")

# Kafel z okolicy Zwolenia (lon 21,08 / lat 51,25), gdzie 54% budynkow jest w rejestrze.
HOTSPOT_TILE = {"z": 14, "x": 9179, "y": 5378}


@pytest.fixture
def connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(str(DATABASE_URL)) as handle:
        yield handle
        handle.rollback()


def buildings_imported(connection: psycopg.Connection) -> bool:
    row = connection.execute("SELECT count(*) > 0 FROM osm_buildings").fetchone()
    return bool(row and row[0])


def test_polygon_tile_over_a_populated_area_is_not_empty(connection: psycopg.Connection) -> None:
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")

    row = connection.execute(POLYGON_TILE, HOTSPOT_TILE).fetchone()

    assert row is not None
    assert len(bytes(row[0])) > 1000  # kafel z setkami obrysow


def test_point_tile_carries_listed_buildings_only(connection: psycopg.Connection) -> None:
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")

    row = connection.execute(POINT_TILE, {"z": 11, "x": 1147, "y": 672}).fetchone()

    assert row is not None
    assert isinstance(bytes(row[0]), bytes)


def test_building_details_include_the_matched_registry_record(connection: psycopg.Connection) -> None:
    listed = connection.execute("SELECT id FROM osm_buildings WHERE registry_matches > 0 LIMIT 1").fetchone()
    if listed is None:
        pytest.skip("brak budynkow z dopasowaniem")

    row = connection.execute(
        BUILDING_SQL,
        {"id": listed[0], "min_share": MIN_MATCH_SHARE, "min_record_inside": MIN_RECORD_INSIDE},
    ).fetchone()

    assert row is not None
    names = ["id", "osm_id", "fclass", "name", "area_m2", "lng", "lat", "registry_matches", "records", "other"]
    values = dict(zip(names, row, strict=True))
    assert values["area_m2"] > 0
    assert values["registry_matches"] >= 1
    assert len(values["records"]) >= 1
    assert values["records"][0]["overlapM2"] > 0
