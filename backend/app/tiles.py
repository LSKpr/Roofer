"""Kafle wektorowe budynkow.

Przy 2,58 mln poligonow nie da sie wyslac do przegladarki GeoJSON-a calego wojewodztwa, wiec
PostGIS tnie geometrie na kafle przez ST_AsMVT. Zakres zoomu decyduje, co w kaflu jest:

* od POLYGON_MIN_ZOOM — obrysy budynkow, bo dopiero wtedy jeden budynek ma sensowny rozmiar,
* od POINT_MIN_ZOOM do POLYGON_MIN_ZOOM - 1 — same centroidy budynkow zgloszonych w rejestrze,
  zeby z poziomu wojewodztwa bylo widac, gdzie rejestr sie zageszcza,
* nizej — nic; kafel z milionem obiektow nikomu nie pomaga.

Identyfikatorem obiektu w kaflu jest `osm_id`, a nie klucz `id` z sekwencji: klik w budynek wysyla
te liczbe do `/api/buildings/{id}`, a sekwencja przezywa TRUNCATE, wiec po ponownym imporcie stare
kafle w cache przegladarki wskazywalyby nieistniejace budynki (pulapki 21 i 22 w AGENTS.md).
Zmiana znaczenia identyfikatora w kaflu to zmiana kodu, nie danych — dlatego idzie razem z podbiciem
TILE_SCHEMA_VERSION w app/dataversion.py, bez ktorego przegladarka potwierdzilaby swiezosc kafli
ze starymi numerami.
"""

POLYGON_MIN_ZOOM = 14
POINT_MIN_ZOOM = 8
MAX_ZOOM = 22

POLYGON_LAYER = "buildings"
POINT_LAYER = "listed"

# Nazwa kolumny, ktora ST_AsMVT zamienia w identyfikator obiektu (piaty argument wywolania). Jedna
# stala w obu miejscach, bo literowka nie jest bledem: PostGIS po cichu oddaje kafel bez
# identyfikatorow obiektow, a kolumne dokleja jako zwykly atrybut.
FEATURE_ID = "id"

# Kolumna identyfikatora MUSI byc calkowita. ST_AsMVT bierze pierwsza kolumne o tej nazwie w typie
# smallint/integer/bigint; `osm_id` jest kolumna `text`, wiec bez rzutowania zostalby zignorowany
# jako identyfikator i wyladowal jako zwykly atrybut - kafel wygladalby poprawnie, a klik w budynek
# przestalby dzialac. `bigint` miesci sie w uint64 formatu MVT, a wszystkie osm_id sa dodatnie.
_FEATURE_ID_COLUMN = f"b.osm_id::bigint AS {FEATURE_ID}"

_BOUNDS = """
WITH bounds AS (
    SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS mercator,
           ST_Transform(ST_TileEnvelope(%(z)s, %(x)s, %(y)s), 4326) AS wgs84
)
"""

POLYGON_TILE = f"""
{_BOUNDS}, feature AS (
    SELECT {_FEATURE_ID_COLUMN},
           (b.registry_matches > 0) AS listed,
           round(b.area_m2::numeric)::int AS area_m2,
           ST_AsMVTGeom(ST_Transform(b.geom, 3857), bounds.mercator, 4096, 64, true) AS geom
    FROM osm_buildings b, bounds
    WHERE b.geom && bounds.wgs84
)
SELECT ST_AsMVT(feature.*, '{POLYGON_LAYER}', 4096, 'geom', '{FEATURE_ID}')
FROM feature WHERE geom IS NOT NULL
"""

POINT_TILE = f"""
{_BOUNDS}, feature AS (
    SELECT {_FEATURE_ID_COLUMN},
           ST_AsMVTGeom(ST_Transform(b.centroid, 3857), bounds.mercator, 4096, 64, true) AS geom
    FROM osm_buildings b, bounds
    WHERE b.registry_matches > 0 AND b.centroid && bounds.wgs84
)
SELECT ST_AsMVT(feature.*, '{POINT_LAYER}', 4096, 'geom', '{FEATURE_ID}')
FROM feature WHERE geom IS NOT NULL
"""


def tile_sql(zoom: int) -> str | None:
    """Zapytanie dla tego zoomu albo None, gdy kafel ma byc pusty."""
    if zoom >= POLYGON_MIN_ZOOM:
        return POLYGON_TILE
    if zoom >= POINT_MIN_ZOOM:
        return POINT_TILE
    return None


def within_grid(zoom: int, x: int, y: int) -> bool:
    if not 0 <= zoom <= MAX_ZOOM:
        return False
    side = 1 << zoom
    return 0 <= x < side and 0 <= y < side
