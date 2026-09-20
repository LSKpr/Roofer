"""Skan obszaru na prawdziwych danych. Uruchamia sie tylko z TEST_DATABASE_URL, wykonuje same
SELECT-y, a test na synchronicznym polaczeniu konczy sie rollbackiem — zaimportowane wojewodztwo
nie jest ruszane."""

import os
import time
from collections.abc import Iterator

import psycopg
import pytest

from app.area import (
    AREA_SCAN_SQL,
    MAX_LISTED_BUILDINGS,
    BoundingBox,
    bbox_area_km2,
    scan_area,
    scan_from_row,
    scan_parameters,
)
from app.db import create_pool
from app.routes.area import to_response

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL nie jest ustawiony")

# Prostokat ~2 x 2 km w okolicy Zwolenia (lon 21,08 / lat 51,25), gdzie okolo polowa budynkow
# jest zgloszona w rejestrze — czyli dokladnie taki obszar, jaki bedzie klikany na demo.
HOTSPOT = BoundingBox(south=51.2450, west=21.0750, north=51.2630, east=21.1037)

POSTGIS_AREA_SQL = "SELECT ST_Area(ST_MakeEnvelope(%(west)s, %(south)s, %(east)s, %(north)s, 4326)::geography) / 1e6"


@pytest.fixture
def connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(str(DATABASE_URL)) as handle:
        yield handle
        handle.rollback()


def scan(connection: psycopg.Connection, bbox: BoundingBox = HOTSPOT) -> tuple[object, float]:
    parameters = scan_parameters(bbox)
    started = time.perf_counter()
    row = connection.execute(AREA_SCAN_SQL, parameters).fetchone()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return row, elapsed_ms


def test_scan_of_a_dense_area_counts_listed_and_not_listed_buildings(connection: psycopg.Connection) -> None:
    row, elapsed_ms = scan(connection)
    result = scan_from_row(row, bbox_area_km2(HOTSPOT))
    stats = result.stats
    print(f"\nskan 2x2 km (zapytanie, pierwsze wywolanie): {elapsed_ms:.1f} ms")
    print(f"budynki: {stats.total}, zgloszone: {stats.listed} ({stats.listed_share:.1%})")

    assert stats.total > 0
    assert stats.listed > 0
    assert stats.listed + stats.not_listed == stats.total
    assert 0.0 < stats.listed_share < 1.0
    assert stats.roof_area_m2 > 0.0
    assert 0.0 < stats.listed_roof_area_m2 < stats.roof_area_m2
    assert stats.registry_records > 0
    assert 3.9 < result.area_km2 < 4.1


def test_listed_buildings_come_sorted_and_capped(connection: psycopg.Connection) -> None:
    row, _ = scan(connection)
    result = scan_from_row(row, bbox_area_km2(HOTSPOT))
    areas = [item["areaM2"] for item in result.listed_buildings]

    assert len(result.listed_buildings) <= MAX_LISTED_BUILDINGS
    assert areas == sorted(areas, reverse=True)
    assert result.truncated == (result.stats.listed > MAX_LISTED_BUILDINGS)
    # Kazdy budynek na liscie ma centroid, wiec da sie go pokazac na mapie i wyeksportowac do CSV.
    assert all(-90.0 < item["lat"] < 90.0 and -180.0 < item["lng"] < 180.0 for item in result.listed_buildings)


def test_listed_buildings_are_addressed_by_osm_id(connection: psycopg.Connection) -> None:
    """Kazde `id` z listy musi byc osm_id istniejacego zgloszonego budynku.

    To nie jest przepisanie zapytania w tescie: lista idzie do panelu i do CSV, a potem uzytkownik
    klika w nia i front wola `/api/buildings/{id}`. Gdyby tu wyszedl klucz z sekwencji, caly ruch
    dalej dostawalby 404 po najblizszym imporcie.
    """
    row, elapsed_ms = scan(connection)
    result = scan_from_row(row, bbox_area_km2(HOTSPOT))
    identifiers = [item["id"] for item in result.listed_buildings]
    print(f"\nskan 2x2 km z identyfikatorami osm_id: {elapsed_ms:.1f} ms, {len(identifiers)} budynkow")
    if not identifiers:
        pytest.skip("brak zgloszonych budynkow na tym obszarze")

    found = connection.execute(
        """
        SELECT count(*)
        FROM osm_buildings
        WHERE registry_matches > 0 AND osm_id = ANY(%(ids)s::text[])
        """,
        {"ids": [str(value) for value in identifiers]},
    ).fetchone()

    assert all(isinstance(value, int) and value > 0 for value in identifiers)
    assert len(set(identifiers)) == len(identifiers)
    assert found is not None
    assert found[0] == len(identifiers)


def test_python_area_formula_agrees_with_postgis_on_the_spheroid(connection: psycopg.Connection) -> None:
    row = connection.execute(
        POSTGIS_AREA_SQL,
        {"west": HOTSPOT.west, "south": HOTSPOT.south, "east": HOTSPOT.east, "north": HOTSPOT.north},
    ).fetchone()

    assert row is not None
    postgis_km2 = float(row[0])
    ours_km2 = bbox_area_km2(HOTSPOT)
    print(f"\npowierzchnia zaznaczenia: wzor {ours_km2:.4f} km2, PostGIS {postgis_km2:.4f} km2")

    assert abs(ours_km2 - postgis_km2) / postgis_km2 < 0.01  # kula vs WGS84: ponizej 1%


async def test_scan_through_the_pool_stays_within_the_time_budget() -> None:
    """Cala droga endpointu (pula, zapytanie, zbudowanie odpowiedzi) — bez twardej asercji na czas,
    zeby test nie byl kapryszny; liczba idzie na stdout."""
    pool = create_pool(str(DATABASE_URL))
    await pool.open(wait=True)
    timings: list[float] = []
    try:
        for _ in range(4):
            started = time.perf_counter()
            response = to_response(await scan_area(pool, HOTSPOT, timeout=5.0))
            timings.append((time.perf_counter() - started) * 1000.0)
    finally:
        await pool.close()

    print("\nskan 2x2 km przez pule [ms]: " + ", ".join(f"{value:.1f}" for value in timings))
    assert response.stats.total > 0
    assert len(response.listed_buildings) > 0
