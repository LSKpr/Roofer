"""Kafle i szczegoly budynku na prawdziwych danych. Wymaga TEST_DATABASE_URL i zaimportowanego
wojewodztwa.

Jeden test probuje wstawic budynek z duplikatem `osm_id` (ma sie nie udac) — cala transakcja jest
wycofywana, wiec zaimportowane wojewodztwo zostaje nietkniete. Pozostale testy tylko czytaja."""

import math
import os
import time
from collections.abc import Iterator

import psycopg
import pytest

from app.buildings import BUILDING_SQL
from app.ingest import MIN_MATCH_SHARE, MIN_RECORD_INSIDE
from app.tiles import (
    DENSITY_COUNT,
    DENSITY_GRID,
    DENSITY_LAYER,
    DENSITY_MIN_ZOOM,
    DENSITY_TILE,
    POLYGON_MIN_ZOOM,
    POLYGON_TILE,
)

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL nie jest ustawiony")

# Kafel z okolicy Zwolenia (lon 21,08 / lat 51,25), gdzie 54% budynkow jest w rejestrze.
HOTSPOT_TILE = {"z": 14, "x": 9179, "y": 5378}
HOTSPOT_LON, HOTSPOT_LAT = 21.08, 51.25
LISTED_TILE = {"z": 11, "x": 1147, "y": 672}

# Kafle, na ktorych zmierzono kafel centroidow przed zmiana: z8 to 815 371 bajtow. Ten sam lancuch
# kafli sluzy do pomiaru po zmianie, inaczej porownywaloby sie dwa rozne obszary, a nie dwa kafle.
MEASURED_TILES = [
    {"z": 8, "x": 143, "y": 85},
    {"z": 9, "x": 286, "y": 170},
    {"z": 10, "x": 572, "y": 341},
    {"z": 11, "x": 1144, "y": 682},
]

# Zapytanie sprzed zmiany, trzymane TYLKO jako punkt odniesienia pomiaru: kafel niosl surowe
# centroidy wszystkich zgloszonych budynkow. Nigdzie poza pomiarem nie jest uzywane — wersja, ktora
# jedzie do przegladarki, siedzi w app/tiles.py.
CENTROID_TILE_BEFORE = """
WITH bounds AS (
    SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS mercator,
           ST_Transform(ST_TileEnvelope(%(z)s, %(x)s, %(y)s), 4326) AS wgs84
), feature AS (
    SELECT b.osm_id::bigint AS id,
           ST_AsMVTGeom(ST_Transform(b.centroid, 3857), bounds.mercator, 4096, 64, true) AS geom
    FROM osm_buildings b, bounds
    WHERE b.registry_matches > 0 AND b.centroid && bounds.wgs84
)
SELECT ST_AsMVT(feature.*, 'listed', 4096, 'geom', 'id')
FROM feature WHERE geom IS NOT NULL
"""

TILE_OSM_IDS_SQL = """
SELECT coalesce(array_agg(b.osm_id::bigint), '{}'::bigint[])
FROM osm_buildings b,
     (SELECT ST_Transform(ST_TileEnvelope(%(z)s, %(x)s, %(y)s), 4326) AS wgs84) bounds
WHERE b.geom && bounds.wgs84
"""

# Liczba zgloszonych budynkow, ktorych centroid lezy w zakresie kafla. Celowo przez ST_Intersects,
# czyli dokladnie, a nie przez `&&` z zapytania kaflowego: `&&` porownuje obwiednie w float4 i myli
# sie przy krawedzi, wiec w obu zapytaniach mylilby sie tak samo i test nie zobaczylby niczego.
# Tak zapisane oczekiwanie zlapalo pierwsza wersje agregacji (jedno zgloszenie za duzo w kaflu).
LISTED_IN_TILE_SQL = """
SELECT count(*)
FROM osm_buildings b,
     (SELECT ST_Transform(ST_TileEnvelope(%(z)s, %(x)s, %(y)s), 4326) AS wgs84) bounds
WHERE b.registry_matches > 0 AND ST_Intersects(b.centroid, bounds.wgs84)
"""


# Indeks z migracji 006. Nazwa jest w asercjach, bo bez niej `EXPLAIN` nie powie, czy zapytanie
# poszlo po WLASCIWYM indeksie.
OSM_ID_INDEX = "osm_buildings_osm_id_key"

# Feature.GeomType z formatu MVT.
MVT_POINT = 1


def tile_at(lon: float, lat: float, zoom: int) -> dict[str, int]:
    """Kafel siatki slippy map, w ktorym lezy ten punkt.

    Liczone tutaj, a nie wpisane na sztywno, bo test sumy `count` musi isc przez CALY zakres zoomow
    warstwy gestosci (8-13) i na kazdym z nich trafic w ten sam, gesty obszar.
    """
    side = 1 << zoom
    sin_lat = math.sin(math.radians(lat))
    x = int((lon + 180.0) / 360.0 * side)
    y = int((0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * side)
    return {"z": zoom, "x": x, "y": y}


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


def layers(tile: bytes) -> list[bytes]:
    """Warstwy kafla (Tile.layers = 3)."""
    return [value for number, value in protobuf_fields(tile) if number == 3 and isinstance(value, bytes)]


def layer_names(tile: bytes) -> list[str]:
    """Nazwy warstw (Layer.name = 1). Nazwa jest czescia kontraktu z frontendem: po niej MapLibre
    wybiera `source-layer`, wiec literowka daje pusta mape bez jednego bledu w konsoli."""
    return [
        value.decode()
        for layer in layers(tile)
        for number, value in protobuf_fields(layer)
        if number == 1 and isinstance(value, bytes)
    ]


def layer_keys(layer: bytes) -> list[str]:
    """Nazwy atrybutow warstwy (Layer.keys = 3); obiekty wskazuja je indeksem."""
    return [value.decode() for number, value in protobuf_fields(layer) if number == 3 and isinstance(value, bytes)]


def scalar(value_message: bytes) -> int:
    """Liczba calkowita z Value (int_value = 4, uint_value = 5, sint_value = 6 w zygzaku)."""
    for tag, item in protobuf_fields(value_message):
        if not isinstance(item, int):
            continue
        if tag in (4, 5):
            return item
        if tag == 6:
            return (item >> 1) ^ -(item & 1)
    raise AssertionError("atrybut kafla nie jest liczba calkowita")


def layer_values(layer: bytes) -> list[int]:
    """Pula wartosci warstwy (Layer.values = 4)."""
    return [scalar(value) for number, value in protobuf_fields(layer) if number == 4 and isinstance(value, bytes)]


def features(layer: bytes) -> list[bytes]:
    """Obiekty warstwy (Layer.features = 2)."""
    return [value for number, value in protobuf_fields(layer) if number == 2 and isinstance(value, bytes)]


def feature_tags(feature: bytes) -> list[int]:
    """Pary indeksow klucz-wartosc obiektu (Feature.tags = 2, upakowane varinty)."""
    numbers: list[int] = []
    for number, block in protobuf_fields(feature):
        if number != 2 or not isinstance(block, bytes):
            continue
        position = 0
        while position < len(block):
            value, position = read_varint(block, position)
            numbers.append(value)
    return numbers


def attribute_values(tile: bytes, key: str) -> list[int]:
    """Wartosci atrybutu `key` ze wszystkich obiektow kafla, obiekt po obiekcie."""
    found: list[int] = []
    for layer in layers(tile):
        keys = layer_keys(layer)
        if key not in keys:
            continue
        wanted, values = keys.index(key), layer_values(layer)
        for feature in features(layer):
            tags = feature_tags(feature)
            pairs = zip(tags[::2], tags[1::2], strict=True)
            found.extend(values[value_index] for key_index, value_index in pairs if key_index == wanted)
    return found


def feature_types(layer: bytes) -> list[int]:
    """Typy geometrii obiektow (Feature.type = 3; 1 = POINT, 2 = LINESTRING, 3 = POLYGON)."""
    return [
        value
        for feature in features(layer)
        for tag, value in protobuf_fields(feature)
        if tag == 3 and isinstance(value, int)
    ]


def feature_ids(tile: bytes) -> list[int]:
    """Identyfikatory obiektow z kafla MVT (Tile.layers = 3, Layer.features = 2, Feature.id = 1)."""
    found: list[int] = []
    for layer in layers(tile):
        for feature in features(layer):
            found.extend(value for tag, value in protobuf_fields(feature) if tag == 1 and isinstance(value, int))
    return found


def density_tile(connection: psycopg.Connection, tile: dict[str, int]) -> bytes:
    row = connection.execute(DENSITY_TILE, tile).fetchone()
    assert row is not None
    return bytes(row[0]) if row[0] else b""


def measure(connection: psycopg.Connection, query: str, tile: dict[str, int], runs: int = 2) -> tuple[int, float]:
    """Rozmiar kafla i NAJKROTSZY z kilku czasow jego zlozenia.

    Najkrotszy, bo pierwszy przebieg placi za wczytanie stron z dysku, a porownujemy dwa zapytania,
    nie dwa stany cache'a bazy.
    """
    size, best_s = 0, None
    for _ in range(runs):
        started_s = time.perf_counter()
        row = connection.execute(query, tile).fetchone()
        elapsed_s = time.perf_counter() - started_s
        size = len(bytes(row[0])) if row and row[0] else 0
        best_s = elapsed_s if best_s is None else min(best_s, elapsed_s)
    return size, best_s or 0.0


def test_polygon_tile_over_a_populated_area_is_not_empty(connection: psycopg.Connection) -> None:
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")

    row = connection.execute(POLYGON_TILE, HOTSPOT_TILE).fetchone()

    assert row is not None
    assert len(bytes(row[0])) > 1000  # kafel z setkami obrysow


def test_density_tile_over_a_listed_area_carries_the_new_layer(connection: psycopg.Connection) -> None:
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")

    tile = density_tile(connection, LISTED_TILE)

    assert tile
    # Nazwa zmieniona z `listed`: w kaflu nie ma juz budynkow, tylko komorki siatki.
    assert layer_names(tile) == [DENSITY_LAYER]
    # Kazdy obiekt to punkt w srodku komorki — heatmapa MapLibre karmi sie punktami, nie kwadratami.
    assert {kind for layer in layers(tile) for kind in feature_types(layer)} == {MVT_POINT}


def test_density_tile_has_no_feature_identifiers(connection: psycopg.Connection) -> None:
    """Komorka siatki nie jest budynkiem i nie ma numeru, pod ktorym dalo by sie o nia zapytac.

    Rozpakowanie kafla jest tu konieczne, bo ST_AsMVT nie protestuje: gdyby w zapytaniu zostal
    piaty argument albo kolumna `id`, kafel wygladalby tak samo, a frontend dostalby zaproszenie
    do /api/buildings/{id} po numer, ktory nic nie znaczy.
    """
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")

    tile = density_tile(connection, LISTED_TILE)

    assert tile
    assert feature_ids(tile) == []


def test_density_tile_carries_the_count_attribute(connection: psycopg.Connection) -> None:
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")

    tile = density_tile(connection, LISTED_TILE)
    counts = attribute_values(tile, DENSITY_COUNT)

    assert [key for layer in layers(tile) for key in layer_keys(layer)] == [DENSITY_COUNT]
    assert counts  # kazdy obiekt warstwy niesie wage heatmapy, inaczej nie ma czego rysowac
    assert all(count >= 1 for count in counts)
    assert len(counts) == sum(len(features(layer)) for layer in layers(tile))


@pytest.mark.parametrize("zoom", range(DENSITY_MIN_ZOOM, POLYGON_MIN_ZOOM))
def test_density_counts_add_up_to_the_listed_buildings_in_the_tile(connection: psycopg.Connection, zoom: int) -> None:
    """Najwazniejszy test tej warstwy: agregacja nie ma prawa nic zgubic ani policzyc dwa razy.

    Suma `count` z kafla musi byc rowna liczbie zgloszonych budynkow, ktorych centroid lezy w jego
    zakresie. Zle zaczepiona siatka dawalaby komorki lezace na dwoch kaflach naraz: przy krawedzi
    kafla ST_AsMVTGeom albo wyrzucilby taka komorke (heatmapa gubi zgloszenia), albo zostawilby ja
    w buforze i sasiad policzylby ja drugi raz (szew na granicy). Sprawdzane na kazdym zoomie
    warstwy, bo rozmiar komorki zmienia sie z zoomem.
    """
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")
    tile = tile_at(HOTSPOT_LON, HOTSPOT_LAT, zoom)

    counts = attribute_values(density_tile(connection, tile), DENSITY_COUNT)
    expected = connection.execute(LISTED_IN_TILE_SQL, tile).fetchone()

    assert expected is not None
    listed = int(expected[0])
    assert listed > 0, f"kafel {tile} bez zgloszen nie sprawdza niczego"
    assert sum(counts) == listed
    assert len(counts) <= DENSITY_GRID**2  # kafel nie ma prawa niesc wiecej niz siatka ma komorek


def test_density_counts_of_the_four_children_add_up_to_their_parent(connection: psycopg.Connection) -> None:
    """Granica miedzy kaflami widziana z obu stron naraz — i to jest prawdziwy test na szwy.

    Cztery kafle z zoomu z+1 pokrywaja dokladnie jeden kafel z zoomu z, wiec ich sumy `count` maja
    dac sume rodzica. Zgloszenie lezace przy wewnetrznej granicy albo wypadnie z obu dzieci (dziura
    w heatmapie), albo trafi do obu (jasniejsza plama wzdluz granicy) — jedno i drugie widac tutaj,
    a nie widac w sumie z pojedynczego kafla.
    """
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")
    parent = tile_at(HOTSPOT_LON, HOTSPOT_LAT, DENSITY_MIN_ZOOM + 2)
    children = [
        {"z": parent["z"] + 1, "x": 2 * parent["x"] + dx, "y": 2 * parent["y"] + dy} for dx in (0, 1) for dy in (0, 1)
    ]

    in_parent = sum(attribute_values(density_tile(connection, parent), DENSITY_COUNT))
    in_children = [sum(attribute_values(density_tile(connection, child), DENSITY_COUNT)) for child in children]

    assert in_parent > 0
    assert all(count > 0 for count in in_children), in_children  # inaczej test sprawdza jeden kafel
    assert sum(in_children) == in_parent


def test_density_tile_is_far_smaller_than_the_centroids_it_replaced(connection: psycopg.Connection) -> None:
    """Pomiar, dla ktorego ta zmiana powstala: kafel z8 mial 815 371 bajtow surowych centroidow.

    Czas zlozenia kafla z8 w bazie nieco UROSL — pogrupowanie 48 tysiecy punktow kosztuje wiecej,
    niz wyrzucenie ich prosto do kafla. Placimy go swiadomie: bajtow jest okolo 50 razy mniej,
    a przegladarka nie liczy juz heatmapy ze 150 tysiecy punktow w jednym watku.
    """
    if not buildings_imported(connection):
        pytest.skip("brak zaimportowanych budynkow")

    sizes: dict[int, tuple[int, int]] = {}
    for tile in MEASURED_TILES:
        before_size, before_s = measure(connection, CENTROID_TILE_BEFORE, tile)
        after_size, after_s = measure(connection, DENSITY_TILE, tile)
        cells = len(attribute_values(density_tile(connection, tile), DENSITY_COUNT))
        sizes[tile["z"]] = (before_size, after_size)
        print(
            f"z{tile['z']} {tile['x']}/{tile['y']}: przed {before_size:>7} B / {before_s * 1000:6.0f} ms"
            f" -> po {after_size:>6} B / {after_s * 1000:6.0f} ms w {cells} komorkach"
        )

    before_z8, after_z8 = sizes[8]
    assert after_z8 * 5 < before_z8  # z8 to najciezszy kafel warstwy i tam zysk ma byc widoczny
    assert all(after < before for before, after in sizes.values())


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
