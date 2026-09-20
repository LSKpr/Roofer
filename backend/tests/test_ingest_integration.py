"""Import na prawdziwym PostGIS-ie. Kazdy test konczy sie wycofaniem transakcji, wiec
zaimportowane dane produkcyjne nie sa ruszane. Uruchamia sie tylko z TEST_DATABASE_URL."""

import os
from collections.abc import Iterator

import psycopg
import pytest

from app.ingest import BUILDINGS, REGISTRY, ingest, match
from app.snapshots import iter_features

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL nie jest ustawiony")

HEADER = '{"type":"FeatureCollection","name":"test","features":['

# Prostokat w Warszawie, ~11 x 7 m.
GOOD = (
    '{"type":"Feature","id":"ok","properties":{"osm_id":"1","fclass":"building","nr_dzialki":"146501_1.1.1"},'
    '"geometry":{"type":"Polygon","coordinates":[[[21.0,52.2],[21.0001,52.2],[21.0001,52.20006],'
    "[21.0,52.20006],[21.0,52.2]]]}}"
)
# Ten sam obszar, wiec musi trafic w GOOD przy dopasowaniu.
OVERLAPPING = (
    '{"type":"Feature","id":"rejestr.1","properties":{"nr_dzialki":"146501_1.1.1"},'
    '"geometry":{"type":"Polygon","coordinates":[[[21.00002,52.20001],[21.00012,52.20001],'
    "[21.00012,52.20005],[21.00002,52.20005],[21.00002,52.20001]]]}}"
)
# Petla ("bowtie") — geometria niepoprawna, ale naprawialna.
SELF_INTERSECTING = (
    '{"type":"Feature","id":"bowtie","properties":{"osm_id":"2"},'
    '"geometry":{"type":"Polygon","coordinates":[[[21.001,52.2],[21.002,52.2001],[21.002,52.2],'
    "[21.001,52.2001],[21.001,52.2]]]}}"
)
# Zdegenerowany pierscien: PostGIS go wczytuje, ale po naprawie nie zostaje nic.
DEGENERATE = (
    '{"type":"Feature","id":"degenerate","properties":{"osm_id":"3"},'
    '"geometry":{"type":"Polygon","coordinates":[[[21.0,52.2],[21.0,52.2]]]}}'
)
# Geometria bez wspolrzednych — tutaj ST_GeomFromGeoJSON rzuca bledem i wchodzi safe_geojson_geometry.
MALFORMED = '{"type":"Feature","id":"malformed","properties":{"osm_id":"4"},"geometry":{"type":"Polygon"}}'
NO_GEOMETRY = '{"type":"Feature","id":"empty","properties":{"osm_id":"5"},"geometry":null}'
# Obrys dzialki: ~30 000 m2, zawiera GOOD w calosci. Takie rekordy sa w prawdziwym rejestrze
# (najwiekszy ma 73,7 km2) i nie moga czynic budynku zgloszonym.
PARCEL = (
    '{"type":"Feature","id":"rejestr.dzialka","properties":{"nr_dzialki":"142801_1.0008.1591"},'
    '"geometry":{"type":"Polygon","coordinates":[[[20.999,52.199],[21.001,52.199],[21.001,52.201],'
    "[20.999,52.201],[20.999,52.199]]]}}"
)
# Duzy budynek (~5 500 m2) i symboliczny rekord (~11 m2) w jego wnetrzu.
BIG_BUILDING = (
    '{"type":"Feature","id":"big","properties":{"osm_id":"10"},'
    '"geometry":{"type":"Polygon","coordinates":[[[21.01,52.21],[21.0115,52.21],[21.0115,52.2105],'
    "[21.01,52.2105],[21.01,52.21]]]}}"
)
SMALL_RECORD = (
    '{"type":"Feature","id":"rejestr.maly","properties":{"nr_dzialki":"146501_1.2.2"},'
    '"geometry":{"type":"Polygon","coordinates":[[[21.0105,52.2102],[21.01055,52.2102],'
    "[21.01055,52.21023],[21.0105,52.21023],[21.0105,52.2102]]]}}"
)
# Zatoka Gwinejska.
OUTSIDE_POLAND = (
    '{"type":"Feature","id":"far","properties":{"osm_id":"6"},'
    '"geometry":{"type":"Polygon","coordinates":[[[0.0,0.0],[0.001,0.0],[0.001,0.001],[0.0,0.001],[0.0,0.0]]]}}'
)


def snapshot(features: list[str]) -> Iterator[str]:
    """Obiekty przechodza przez ten sam czytnik, ktorego uzywa import z pliku."""
    body = [f"{feature}," for feature in features[:-1]] + features[-1:]
    return iter_features([HEADER, *body, f'],"numberReturned":{len(features)}}}'])


@pytest.fixture
def connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(str(DATABASE_URL)) as handle:
        yield handle
        handle.rollback()


def test_ingest_counts_every_rejected_object(connection: psycopg.Connection) -> None:
    objects = [GOOD, SELF_INTERSECTING, DEGENERATE, MALFORMED, NO_GEOMETRY, OUTSIDE_POLAND]

    report = ingest(connection, BUILDINGS, snapshot(objects))

    assert report.staged == 6
    assert report.unparsable == 2  # brak geometrii i geometria bez wspolrzednych
    assert report.empty_after_repair == 1  # zdegenerowany pierscien
    assert report.outside_poland == 1
    assert report.inserted == 2  # poprawny prostokat i naprawiona petla
    assert report.repaired == 1  # naprawa dotyczy tylko tego, co wyladowalo w tabeli
    # Powody odrzucenia musza sie sumowac do liczby wczytanych linii.
    assert report.rejected == report.unparsable + report.empty_after_repair + report.outside_poland


def test_ingest_fills_centroid_and_area(connection: psycopg.Connection) -> None:
    ingest(connection, BUILDINGS, snapshot([GOOD]))

    row = connection.execute(
        "SELECT osm_id, ST_GeometryType(geom), round(area_m2::numeric, 1), ST_X(centroid), ST_Y(centroid)"
        " FROM osm_buildings"
    ).fetchone()

    assert row is not None
    osm_id, geometry_type, area_m2, longitude, latitude = row
    assert (osm_id, geometry_type) == ("1", "ST_MultiPolygon")
    assert 40 < float(area_m2) < 60  # ~11 x 6,7 m
    assert (round(longitude, 4), round(latitude, 4)) == (21.0001, 52.2000)


def test_matching_links_a_registry_record_to_the_building(connection: psycopg.Connection) -> None:
    ingest(connection, BUILDINGS, snapshot([GOOD, SELF_INTERSECTING]))
    ingest(connection, REGISTRY, snapshot([OVERLAPPING]))

    result = match(connection)

    assert result.pairs == 1
    assert result.buildings_with_match == 1
    counts = connection.execute("SELECT osm_id, registry_matches FROM osm_buildings ORDER BY osm_id").fetchall()
    assert counts == [("1", 1), ("2", 0)]


def test_a_parcel_sized_record_does_not_make_a_building_listed(connection: psycopg.Connection) -> None:
    ingest(connection, BUILDINGS, snapshot([GOOD]))
    ingest(connection, REGISTRY, snapshot([PARCEL]))

    result = match(connection)

    assert result.pairs == 1  # przeciecie zostaje zapisane jako material dowodowy...
    assert result.qualifying_pairs == 0  # ...ale regula je odrzuca
    assert result.buildings_with_match == 0


def test_a_symbolic_record_inside_a_large_building_still_counts(connection: psycopg.Connection) -> None:
    ingest(connection, BUILDINGS, snapshot([BIG_BUILDING]))
    ingest(connection, REGISTRY, snapshot([SMALL_RECORD]))

    result = match(connection)

    shares = connection.execute("SELECT share_building, share_record FROM building_registry_match").fetchone()
    assert shares is not None
    assert shares[0] < 0.01  # rekord zajmuje ulamek dachu...
    assert shares[1] > 0.9  # ...ale niemal caly lezy w budynku
    assert result.buildings_with_match == 1
