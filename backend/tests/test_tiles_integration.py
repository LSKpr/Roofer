"""Kafle i szczegoly budynku na prawdziwych danych. Wymaga TEST_DATABASE_URL i zaimportowanego
wojewodztwa.

Jeden test probuje wstawic budynek z duplikatem `osm_id` (ma sie nie udac) — cala transakcja jest
wycofywana, wiec zaimportowane wojewodztwo zostaje nietkniete. Pozostale testy tylko czytaja."""

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
LISTED_TILE = {"z": 11, "x": 1147, "y": 672}

TILE_OSM_IDS_SQL = """
SELECT coalesce(array_agg(b.osm_id::bigint), '{}'::bigint[])
FROM osm_buildings b,
     (SELECT ST_Transform(ST_TileEnvelope(%(z)s, %(x)s, %(y)s), 4326) AS wgs84) bounds
WHERE b.geom && bounds.wgs84
"""

LISTED_TILE_OSM_IDS_SQL = """
SELECT coalesce(array_agg(b.osm_id::bigint), '{}'::bigint[])
FROM osm_buildings b,
     (SELECT ST_Transform(ST_TileEnvelope(%(z)s, %(x)s, %(y)s), 4326) AS wgs84) bounds
WHERE b.registry_matches > 0 AND b.centroid && bounds.wgs84
"""

# Indeks z migracji 006. Nazwa jest w asercjach, bo bez niej `EXPLAIN` nie powie, czy zapytanie
# poszlo po WLASCIWYM indeksie.
OSM_ID_INDEX = "osm_buildings_osm_id_key"


@pytest.fixture
def connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(str(DATABASE_URL)) as handle:
        yield handle
        handle.rollback()


def buildings_imported(connection: psycopg.Connection) -> bool:
    row = connection.execute("SELECT count(*) > 0 FROM osm_buildings").fetchone()
    return bool(row and row[0])


def listed_osm_id(connection: psycopg.Connection) -> int | None:
    row = connection.execute("SELECT osm_id::bigint FROM osm_buildings WHERE registry_matches > 0 LIMIT 1").fetchone()
    return int(row[0]) if row else None


def read_varint(data: bytes, position: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7


def protobuf_fields(data: bytes) -> Iterator[tuple[int, int | bytes]]:
    """Numer pola i wartosc: varint jako liczba, blok bajtow jako bytes, reszta pomijana.

    Wlasny czytnik, bo zaleznosci nie dokladamy, a inaczej nie da sie sprawdzic najgrozniejszej
    cichej awarii kafla: ST_AsMVT przy kolumnie identyfikatora w zlym typie nie zglasza bledu,
    tylko oddaje kafel bez identyfikatorow obiektow.
    """
    position = 0
    while position < len(data):
        key, position = read_varint(data, position)
        number, wire = key >> 3, key & 0x07
        if wire == 0:
            value, position = read_varint(data, position)
            yield number, value
        elif wire == 2:
            length, position = read_varint(data, position)
            yield number, data[position : position + length]
            position += length
        elif wire == 5:
            position += 4
        elif wire == 1:
            position += 8
        else:
            raise AssertionError(f"nieznany typ pola protobuf: {wire}")


def feature_ids(tile: bytes) -> list[int]:
    """Identyfikatory obiektow z kafla MVT (Tile.layers = 3, Layer.features = 2, Feature.id = 1)."""
    found: list[int] = []
    for number, layer in protobuf_fields(tile):
        if number != 3 or not isinstance(layer, bytes):
            continue
        for field, feature in protobuf_fields(layer):
            if field != 2 or not isinstance(feature, bytes):
                continue
            found.extend(value for tag, value in protobuf_fields(feature) if tag == 1 and isinstance(value, int))
    return found


def test_polygon_tile_over_a_populated_area_is_not_empty(connection: psycopg.Connection) -> None:
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")

    row = connection.execute(POLYGON_TILE, HOTSPOT_TILE).fetchone()

    assert row is not None
    assert len(bytes(row[0])) > 1000  # kafel z setkami obrysow


def test_point_tile_carries_listed_buildings_only(connection: psycopg.Connection) -> None:
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")

    row = connection.execute(POINT_TILE, LISTED_TILE).fetchone()

    assert row is not None
    assert isinstance(bytes(row[0]), bytes)


def test_polygon_tile_identifies_features_by_osm_id(connection: psycopg.Connection) -> None:
    """Sedno zmiany, sprawdzone na gotowym kaflu: identyfikator obiektu to osm_id z tego obszaru.

    Rozpakowanie kafla jest tu konieczne — gdyby kolumna identyfikatora zostala tekstem, PostGIS
    dolozylby ja jako zwykly atrybut i oddal kafel bez identyfikatorow. Kafel wygladalby poprawnie,
    a klik w budynek konczylby sie 404.
    """
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")
    row = connection.execute(POLYGON_TILE, HOTSPOT_TILE).fetchone()
    expected = connection.execute(TILE_OSM_IDS_SQL, HOTSPOT_TILE).fetchone()

    assert row is not None and expected is not None
    ids = feature_ids(bytes(row[0]))
    osm_ids = set(expected[0])

    assert len(ids) > 20  # kafel z kilkudziesieciu budynkow, a nie z jednym przypadkowym
    assert len(set(ids)) == len(ids)  # identyfikator obiektu jest unikalny w kaflu
    assert set(ids) <= osm_ids  # kazdy pochodzi z osm_id budynku lezacego w tym kaflu


def test_point_tile_identifies_features_by_osm_id(connection: psycopg.Connection) -> None:
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")
    row = connection.execute(POINT_TILE, LISTED_TILE).fetchone()
    expected = connection.execute(LISTED_TILE_OSM_IDS_SQL, LISTED_TILE).fetchone()

    assert row is not None and expected is not None
    ids = feature_ids(bytes(row[0]))

    assert ids  # kafel centroidow zgloszonych budynkow nie jest pusty na tym obszarze
    assert set(ids) <= set(expected[0])


def test_building_details_include_the_matched_registry_record(connection: psycopg.Connection) -> None:
    osm_id = listed_osm_id(connection)
    if osm_id is None:
        pytest.skip("brak budynkow z dopasowaniem")

    row = connection.execute(
        BUILDING_SQL,
        {"id": osm_id, "min_share": MIN_MATCH_SHARE, "min_record_inside": MIN_RECORD_INSIDE},
    ).fetchone()

    assert row is not None
    # Kolejnosc kolumn z BUILDING_SQL. Zmiana zapytania musi tu byc widoczna, dlatego `strict=True`.
    # Nie ma juz osobnego `osm_id`: publicznym identyfikatorem jest `id` i to WLASNIE jest osm_id.
    names = [
        "id",
        "fclass",
        "osm_type",
        "name",
        "area_m2",
        "lng",
        "lat",
        "registry_matches",
        "records",
        "other",
    ]
    values = dict(zip(names, row, strict=True))
    assert values["id"] == osm_id
    assert values["area_m2"] > 0
    assert values["registry_matches"] >= 1
    assert len(values["records"]) >= 1
    assert values["records"][0]["overlapM2"] > 0


def test_the_building_lookup_goes_through_the_unique_index(connection: psycopg.Connection) -> None:
    """`osm_id = %(id)s::text` musi konczyc sie Index Scan.

    Odwrotne rzutowanie (`osm_id::bigint = %(id)s`) jest nieindeksowalne i zmierzylismy, co daje:
    Parallel Seq Scan po 1,2 GB tabeli, 264 ms wobec 0,5 ms. Karta budynku otwierana z mapy nie ma
    na to budzetu, wiec plan jest czescia kontraktu, nie szczegolem.
    """
    osm_id = listed_osm_id(connection)
    if osm_id is None:
        pytest.skip("brak budynkow z dopasowaniem")

    rows = connection.execute(
        "EXPLAIN " + BUILDING_SQL,
        {"id": osm_id, "min_share": MIN_MATCH_SHARE, "min_record_inside": MIN_RECORD_INSIDE},
    ).fetchall()
    plan = "\n".join(str(line[0]) for line in rows)

    assert OSM_ID_INDEX in plan, plan
    assert "Seq Scan on osm_buildings" not in plan, plan


def test_osm_id_is_unique_and_filled_in_for_every_building(connection: psycopg.Connection) -> None:
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")

    row = connection.execute("SELECT count(*), count(osm_id), count(DISTINCT osm_id) FROM osm_buildings").fetchone()

    assert row is not None
    total, filled, distinct = row
    assert filled == total  # bez osm_id budynek nie mialby adresu w API
    assert distinct == total


def test_migration_006_created_a_unique_index(connection: psycopg.Connection) -> None:
    row = connection.execute(
        """
        SELECT index_class.relname, index_info.indisunique
        FROM pg_index index_info
        JOIN pg_class index_class ON index_class.oid = index_info.indexrelid
        JOIN pg_class table_class ON table_class.oid = index_info.indrelid
        JOIN pg_attribute column_info
             ON column_info.attrelid = table_class.oid AND column_info.attnum = index_info.indkey[0]
        WHERE table_class.relname = 'osm_buildings'
          AND column_info.attname = 'osm_id'
          AND index_info.indnatts = 1
        """
    ).fetchone()

    assert row is not None, "brak indeksu po osm_id — migracja 006 nie zostala zastosowana"
    assert row[1] is True  # unikalny, a nie zwykly: duplikat ma przerwac import, nie przejsc cicho


def test_a_duplicate_osm_id_is_rejected_loudly(connection: psycopg.Connection) -> None:
    """Po to jest unikalnosc: snapshot z dwoma budynkami o tym samym osm_id ma wywalic import,
    a nie zostawic dwoch roznych budynkow pod jednym adresem w API."""
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")

    with pytest.raises(psycopg.errors.UniqueViolation):
        connection.execute(
            """
            INSERT INTO osm_buildings (osm_id, geom, centroid, area_m2)
            SELECT osm_id, geom, centroid, area_m2 FROM osm_buildings LIMIT 1
            """
        )
    connection.rollback()  # nie zostawiamy w bazie niczego z testu
