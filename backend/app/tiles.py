"""Kafle wektorowe budynkow.

Przy 2,58 mln poligonow nie da sie wyslac do przegladarki GeoJSON-a calego wojewodztwa, wiec
PostGIS tnie geometrie na kafle przez ST_AsMVT. Zakres zoomu decyduje, co w kaflu jest:

* od POLYGON_MIN_ZOOM — obrysy budynkow, bo dopiero wtedy jeden budynek ma sensowny rozmiar,
* od POINT_MIN_ZOOM do POLYGON_MIN_ZOOM - 1 — same centroidy budynkow zgloszonych w rejestrze,
  zeby z poziomu wojewodztwa bylo widac, gdzie rejestr sie zageszcza,
* nizej — nic; kafel z milionem obiektow nikomu nie pomaga.
"""

POLYGON_MIN_ZOOM = 14
POINT_MIN_ZOOM = 8
MAX_ZOOM = 22

POLYGON_LAYER = "buildings"
POINT_LAYER = "listed"

_BOUNDS = """
WITH bounds AS (
    SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS mercator,
           ST_Transform(ST_TileEnvelope(%(z)s, %(x)s, %(y)s), 4326) AS wgs84
)
"""

POLYGON_TILE = f"""
{_BOUNDS}, feature AS (
    SELECT b.id,
           (b.registry_matches > 0) AS listed,
           round(b.area_m2::numeric)::int AS area_m2,
           ST_AsMVTGeom(ST_Transform(b.geom, 3857), bounds.mercator, 4096, 64, true) AS geom
    FROM osm_buildings b, bounds
    WHERE b.geom && bounds.wgs84
)
SELECT ST_AsMVT(feature.*, '{POLYGON_LAYER}', 4096, 'geom', 'id') FROM feature WHERE geom IS NOT NULL
"""

POINT_TILE = f"""
{_BOUNDS}, feature AS (
    SELECT b.id,
           ST_AsMVTGeom(ST_Transform(b.centroid, 3857), bounds.mercator, 4096, 64, true) AS geom
    FROM osm_buildings b, bounds
    WHERE b.registry_matches > 0 AND b.centroid && bounds.wgs84
)
SELECT ST_AsMVT(feature.*, '{POINT_LAYER}', 4096, 'geom', 'id') FROM feature WHERE geom IS NOT NULL
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
