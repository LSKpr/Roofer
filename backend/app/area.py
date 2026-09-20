"""Skan zaznaczonego na mapie prostokata: statystyki i lista budynkow zgloszonych w rejestrze.

Trzy decyzje, ktore warto znac przed zmiana tego pliku:

* Limit powierzchni zaznaczenia siedzi w JEDNEJ stalej MAX_AREA_KM2 i jest wystawiony endpointem
  `GET /area/limits`. Front nie ma trzymac wlasnej kopii tej liczby — inaczej przepuszcza zadanie,
  ktore backend odrzuca.
* Powierzchnie zaznaczenia liczymy w Pythonie (bbox_area_km2), a nie w bazie. Dzieki temu zbyt
  duzy prostokat odrzucamy BEZ odpytywania bazy, a liczba w komunikacie bledu i pole `areaKm2`
  w odpowiedzi pochodza z tego samego zrodla.
* Statystyki to jedno zapytanie. Warunek `geom && ST_MakeEnvelope(...)` porownuje bboksy, wiec
  korzysta z indeksu GiST; przy krawedzi zaznaczenia moze wpasc budynek, ktory styka sie z nim
  tylko bboksem, ale przy dachach rzedu 10 m to pomijalne i zgadza sie z tym, co pokazuja kafle
  (app/tiles.py uzywa tego samego operatora).
* `listedBuildings[].id` to `osm_id`, tak samo jak identyfikator obiektu w kaflu i adres w
  `/api/buildings/{id}`. Ksztalt odpowiedzi sie nie zmienil, zmienilo sie znaczenie liczby: klucz
  z sekwencji bazy po ponownym imporcie wskazywal inny budynek (pulapka 21 w AGENTS.md).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from math import radians, sin
from typing import Any

from app.ingest import MATCH_RULE, MIN_MATCH_SHARE, MIN_RECORD_INSIDE

# Maksymalna powierzchnia zaznaczenia. Jedyne miejsce, w ktorym ta liczba istnieje.
MAX_AREA_KM2 = 25.0

# Lista budynkow sluzy panelowi i eksportowi CSV, wiec ma gorna granice; nadwyzke zglasza
# pole `truncated`, zeby nikt nie wzial przycietej listy za komplet.
MAX_LISTED_BUILDINGS = 500

# Sredni promien Ziemi (IUGG), ten sam, ktorego uzywa PostGIS jako promienia kuli.
EARTH_RADIUS_M = 6371008.8

_ENVELOPE = "ST_MakeEnvelope(%(west)s, %(south)s, %(east)s, %(north)s, 4326)"

AREA_SCAN_SQL = f"""
WITH stats AS (
    SELECT count(*)::int                                                            AS total,
           (count(*) FILTER (WHERE b.registry_matches > 0))::int                    AS listed,
           round(coalesce(sum(b.area_m2), 0)::numeric, 1)::float8                   AS roof_area_m2,
           round(coalesce(sum(b.area_m2) FILTER (WHERE b.registry_matches > 0), 0)::numeric, 1)::float8
                                                                                    AS listed_roof_area_m2
    FROM osm_buildings b
    WHERE b.geom && {_ENVELOPE}
), listed AS (
    -- `id` na liscie to osm_id, bo ta liczba idzie potem do /api/buildings/{id} i do CSV, a klucz
    -- z sekwencji nie przezywa ponownego importu (pulapka 21 w AGENTS.md). Dla porzadku takze
    -- tie-breaker sortowania jest po osm_id — inaczej kolejnosc budynkow o rownej powierzchni
    -- zmienialaby sie po kazdym imporcie. Zlaczenia w podzapytaniu zostaja na wewnetrznym b.id.
    SELECT b.osm_id::bigint                     AS id,
           round(b.area_m2::numeric, 1)::float8 AS area_m2,
           ST_X(b.centroid)                     AS lng,
           ST_Y(b.centroid)                     AS lat,
           (
               SELECT r.nr_dzialki
               FROM building_registry_match m
               JOIN registry_records r ON r.id = m.record_id
               WHERE m.building_id = b.id AND {MATCH_RULE}
               ORDER BY m.overlap_m2 DESC
               LIMIT 1
           ) AS nr_dzialki
    FROM osm_buildings b
    WHERE b.registry_matches > 0 AND b.geom && {_ENVELOPE}
    ORDER BY b.area_m2 DESC, id
    LIMIT %(limit)s
)
SELECT stats.total,
       stats.listed,
       stats.roof_area_m2,
       stats.listed_roof_area_m2,
       (SELECT count(*)::int FROM registry_records r WHERE r.geom && {_ENVELOPE}) AS registry_records,
       (
           SELECT coalesce(json_agg(json_build_object(
                      'id',        listed.id,
                      'areaM2',    listed.area_m2,
                      'lng',       listed.lng,
                      'lat',       listed.lat,
                      'nrDzialki', listed.nr_dzialki
                  ) ORDER BY listed.area_m2 DESC, listed.id), '[]'::json)
           FROM listed
       ) AS listed_buildings
FROM stats
"""


@dataclass(frozen=True)
class BoundingBox:
    """Zaznaczenie w stopniach WGS84. Nazwy krawedzi, a nie naroznikow, bo tak mowi SQL."""

    south: float
    west: float
    north: float
    east: float


@dataclass(frozen=True)
class AreaStats:
    """`not_listed` znaczy „nie ma go w rejestrze", a nie „dach jest czysty"."""

    total: int
    listed: int
    not_listed: int
    listed_share: float
    roof_area_m2: float
    listed_roof_area_m2: float
    registry_records: int


@dataclass(frozen=True)
class AreaScan:
    stats: AreaStats
    listed_buildings: list[dict[str, Any]]
    truncated: bool
    area_km2: float


EMPTY_STATS = AreaStats(
    total=0,
    listed=0,
    not_listed=0,
    listed_share=0.0,
    roof_area_m2=0.0,
    listed_roof_area_m2=0.0,
    registry_records=0,
)


def bbox_area_km2(bbox: BoundingBox) -> float:
    """Powierzchnia prostokata na kuli: R^2 * (lam2 - lam1) * (sin(fi2) - sin(fi1)).

    PostGIS policzylby to na elipsoidzie (ST_Area(geography)), ale roznica kula/WGS84 to ponizej
    0,5% i dla bramki 25 km2 nie ma znaczenia — test integracyjny porownuje oba wyniki. Za to
    wzor w Pythonie pozwala odrzucic zbyt duze zaznaczenie bez ruszania bazy.
    """
    height = radians(bbox.north) - radians(bbox.south)
    width = radians(bbox.east) - radians(bbox.west)
    if height <= 0.0 or width <= 0.0:
        return 0.0
    area_m2 = EARTH_RADIUS_M**2 * width * (sin(radians(bbox.north)) - sin(radians(bbox.south)))
    return area_m2 / 1_000_000.0


def format_km2(value: float) -> str:
    """Liczba kilometrow kwadratowych po polsku: przecinek dziesietny i bez zbednego „,0"."""
    return f"{value:.1f}".replace(".", ",").removesuffix(",0")


def bbox_problem(bbox: BoundingBox) -> str | None:
    """Komunikat po polsku, gdy prostokat nie ma sensu; None, gdy jest w porzadku."""
    if not (-90.0 <= bbox.south <= 90.0 and -90.0 <= bbox.north <= 90.0):
        return "Szerokosc geograficzna musi miescic sie w zakresie od -90 do 90 stopni."
    if not (-180.0 <= bbox.west <= 180.0 and -180.0 <= bbox.east <= 180.0):
        return "Dlugosc geograficzna musi miescic sie w zakresie od -180 do 180 stopni."
    if bbox.north <= bbox.south:
        return "Naroznik NE musi lezec na polnoc od naroznika SW — wspolrzedne sa odwrocone."
    if bbox.east <= bbox.west:
        return "Naroznik NE musi lezec na wschod od naroznika SW — wspolrzedne sa odwrocone."
    return None


def area_problem(area_km2: float, limit_km2: float = MAX_AREA_KM2) -> str | None:
    """Komunikat z obiema liczbami, zeby uzytkownik wiedzial, o ile przesadzil."""
    if area_km2 <= limit_km2:
        return None
    return (
        f"Obszar ma {format_km2(area_km2)} km2, a maksimum to {format_km2(limit_km2)} km2 — zaznacz mniejszy fragment."
    )


def scan_parameters(bbox: BoundingBox, limit: int = MAX_LISTED_BUILDINGS) -> dict[str, Any]:
    """Pobieramy o jeden budynek wiecej, niz oddamy — tylko tak wiadomo, ze lista jest przycieta."""
    return {
        "south": bbox.south,
        "west": bbox.west,
        "north": bbox.north,
        "east": bbox.east,
        "limit": limit + 1,
        "min_share": MIN_MATCH_SHARE,
        "min_record_inside": MIN_RECORD_INSIDE,
    }


def scan_from_row(
    row: Sequence[Any] | None,
    area_km2: float,
    limit: int = MAX_LISTED_BUILDINGS,
) -> AreaScan:
    """Wiersz z AREA_SCAN_SQL na statystyki. Pusty obszar to zera, nie blad."""
    if row is None:
        return AreaScan(stats=EMPTY_STATS, listed_buildings=[], truncated=False, area_km2=round(area_km2, 3))
    total, listed, roof_area_m2, listed_roof_area_m2, registry_records, buildings = row[:6]
    total, listed = int(total), int(listed)
    found = list(buildings or [])
    return AreaScan(
        stats=AreaStats(
            total=total,
            listed=listed,
            not_listed=total - listed,
            listed_share=round(listed / total, 4) if total else 0.0,
            roof_area_m2=float(roof_area_m2),
            listed_roof_area_m2=float(listed_roof_area_m2),
            registry_records=int(registry_records),
        ),
        listed_buildings=found[:limit],
        truncated=len(found) > limit,
        area_km2=round(area_km2, 3),
    )


async def scan_area(
    pool: Any,
    bbox: BoundingBox,
    timeout: float,
    limit: int = MAX_LISTED_BUILDINGS,
) -> AreaScan:
    async with pool.connection(timeout=timeout) as connection:
        cursor = await connection.execute(AREA_SCAN_SQL, scan_parameters(bbox, limit))
        row = await cursor.fetchone()
    return scan_from_row(row, bbox_area_km2(bbox), limit)
