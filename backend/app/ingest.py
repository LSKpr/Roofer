"""Import snapshotow do PostGIS.

Python nie parsuje tu JSON-a. Surowe linie ida binarnym COPY do nieżurnalowanej tabeli
tymczasowej, a geometrie, centroidy i powierzchnie liczy PostGIS jednym przebiegiem. Przy
2,58 mln obiektow to rozni sie rzedem wielkosci od wstawiania rekord po rekordzie.

Zadna funkcja z tego modulu nie commituje — o transakcji decyduje wywolujacy, dzieki czemu
testy integracyjne moga wszystko wycofac.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

# Snapshoty pochodza z jednego wojewodztwa; obiekt poza Polska to blad danych, nie granica zakresu.
POLAND_BBOX = "ST_MakeEnvelope(14.0, 49.0, 24.3, 55.0, 4326)"
USABLE = f"geom IS NOT NULL AND NOT ST_IsEmpty(geom) AND ST_Intersects(geom, {POLAND_BBOX})"

# Kiedy rekord rejestru liczy sie jako dopasowany do budynku.
#
# Czesc geometrii w publicznej warstwie GeoAzbest to obrysy DZIALEK, nie dachow: w snapshocie
# mazowieckiego jest rekord o powierzchni 73,7 km2 przy medianie 99 m2. Taki poligon przykrywa
# w calosci kazdy budynek w okolicy, co daje 33 899 falszywych par. Dlatego przekrycie musi
# obejmowac co najmniej MIN_MATCH_SHARE obu poligonow — co jest rownowazne temu, ze wiekszy
# poligon nie jest wiecej niz 10x wiekszy od mniejszego.
#
# Wyjatek dla malych rekordow (1 754 par): jesli co najmniej MIN_RECORD_INSIDE poligonu rejestru
# lezy w budynku, to dopasowanie zostaje, choc zajmuje maly procent dachu. Obrysy w rejestrze sa
# rysowane recznie i bywaja symboliczne.
MIN_MATCH_SHARE = 0.1
MIN_RECORD_INSIDE = 0.5
MATCH_RULE = "(least(share_building, share_record) >= %(min_share)s OR share_record >= %(min_record_inside)s)"

CREATE_RAW_STAGING = "CREATE UNLOGGED TABLE IF NOT EXISTS stg_raw_features (raw text)"
TRUNCATE_RAW_STAGING = "TRUNCATE stg_raw_features"
COPY_RAW = "COPY stg_raw_features (raw) FROM STDIN (FORMAT BINARY)"
DROP_PARSED_STAGING = "DROP TABLE IF EXISTS stg_parsed_features"
DROP_RAW_STAGING = "DROP TABLE IF EXISTS stg_raw_features"

CREATE_PARSED_STAGING = """
CREATE UNLOGGED TABLE stg_parsed_features AS
WITH feature AS (
    SELECT raw::jsonb AS j FROM stg_raw_features
), located AS (
    SELECT j, safe_geojson_geometry(j->>'geometry') AS source_geom FROM feature
)
SELECT
    j->>'id'                                 AS source_id,
    coalesce(j->'properties', '{}'::jsonb)   AS properties,
    CASE
        WHEN source_geom IS NULL          THEN NULL
        WHEN ST_IsValid(source_geom)      THEN ST_Multi(source_geom)
        ELSE ST_Multi(ST_CollectionExtract(ST_MakeValid(source_geom), 3))
    END                                      AS geom,
    source_geom IS NOT NULL AND NOT ST_IsValid(source_geom) AS repaired
FROM located
"""

# Powody odrzucenia sa rozlaczne, zeby sumowaly sie do liczby wczytanych linii. `repaired`
# opisuje wylacznie obiekty, ktore trafily do tabeli — naprawa geometrii, ktora i tak zostaje
# odrzucona, nie jest zadna informacja.
DIAGNOSE = f"""
SELECT count(*)                                                        AS staged,
       count(*) FILTER (WHERE geom IS NULL)                            AS unparsable,
       count(*) FILTER (WHERE geom IS NOT NULL AND ST_IsEmpty(geom))   AS empty_after_repair,
       count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)
                          AND NOT ST_Intersects(geom, {POLAND_BBOX}))  AS outside_poland,
       count(*) FILTER (WHERE {USABLE})                                AS usable,
       count(*) FILTER (WHERE repaired AND {USABLE})                   AS repaired
FROM stg_parsed_features
"""

INSERT_BUILDINGS = f"""
INSERT INTO osm_buildings (osm_id, fclass, name, geom, centroid, area_m2, repaired)
SELECT properties->>'osm_id',
       properties->>'fclass',
       properties->>'name',
       geom,
       ST_Centroid(geom),
       ST_Area(geom::geography),
       repaired
FROM stg_parsed_features
WHERE {USABLE}
"""

INSERT_REGISTRY = f"""
INSERT INTO registry_records (source_id, nr_dzialki, properties, geom, centroid, area_m2, repaired)
SELECT source_id,
       properties->>'nr_dzialki',
       properties,
       geom,
       ST_Centroid(geom),
       ST_Area(geom::geography),
       repaired
FROM stg_parsed_features
WHERE {USABLE}
"""

MATCH = """
INSERT INTO building_registry_match (building_id, record_id, overlap_m2, share_building, share_record)
SELECT b.id,
       r.id,
       o.overlap_m2,
       CASE WHEN b.area_m2 > 0 THEN o.overlap_m2 / b.area_m2 ELSE 0 END,
       CASE WHEN r.area_m2 > 0 THEN o.overlap_m2 / r.area_m2 ELSE 0 END
FROM osm_buildings b
JOIN registry_records r ON ST_Intersects(b.geom, r.geom)
CROSS JOIN LATERAL (SELECT ST_Area(ST_Intersection(b.geom, r.geom)::geography) AS overlap_m2) o
WHERE o.overlap_m2 > 0
ON CONFLICT DO NOTHING
"""

RESET_MATCH_COUNTS = "UPDATE osm_buildings SET registry_matches = 0 WHERE registry_matches <> 0"

APPLY_MATCH_COUNTS = f"""
UPDATE osm_buildings b
SET registry_matches = counted.n
FROM (
    SELECT building_id, count(*)::int AS n
    FROM building_registry_match
    WHERE {MATCH_RULE}
    GROUP BY building_id
) counted
WHERE b.id = counted.building_id
"""

COUNT_QUALIFYING_PAIRS = f"SELECT count(*) FROM building_registry_match WHERE {MATCH_RULE}"


@dataclass(frozen=True)
class Dataset:
    label: str
    table: str
    insert_sql: str


BUILDINGS = Dataset("budynki OSM", "osm_buildings", INSERT_BUILDINGS)
REGISTRY = Dataset("rejestr GeoAzbest", "registry_records", INSERT_REGISTRY)
DATASETS = {"buildings": BUILDINGS, "registry": REGISTRY}


@dataclass(frozen=True)
class IngestReport:
    dataset: str
    staged: int
    inserted: int
    usable: int
    repaired: int
    unparsable: int
    empty_after_repair: int
    outside_poland: int

    @property
    def rejected(self) -> int:
        return self.staged - self.inserted


@dataclass(frozen=True)
class MatchReport:
    pairs: int
    qualifying_pairs: int
    buildings_with_match: int


def stage_raw(connection: Any, lines: Iterable[str], progress: Callable[[int], None] | None = None) -> int:
    """Wrzuca surowe linie do tabeli tymczasowej. Format binarny oszczedza escapowanie JSON-a."""
    staged = 0
    with connection.cursor() as cursor:
        cursor.execute(CREATE_RAW_STAGING)
        cursor.execute(TRUNCATE_RAW_STAGING)
        with cursor.copy(COPY_RAW) as copy:
            copy.set_types(["text"])
            for line in lines:
                copy.write_row((line,))
                staged += 1
                if progress is not None and staged % 200_000 == 0:
                    progress(staged)
    return staged


def cleanup_staging(connection: Any) -> None:
    """Tabele tymczasowe trzymaja kopie calego snapshotu — po imporcie to ponad 1,5 GB bez zastosowania."""
    with connection.cursor() as cursor:
        cursor.execute(DROP_PARSED_STAGING)
        cursor.execute(DROP_RAW_STAGING)


def analyze(connection: Any, *tables: str) -> None:
    """Po masowym ladowaniu statystyki planera sa nieaktualne i kazde pozniejsze zapytanie planuje sie zle."""
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"ANALYZE {table}")


def parse_staged(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(DROP_PARSED_STAGING)
        cursor.execute(CREATE_PARSED_STAGING)


def diagnose(connection: Any) -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(DIAGNOSE)
        row = cursor.fetchone()
        names = [column.name for column in cursor.description or []]
    return dict(zip(names, row, strict=True))


def ingest(
    connection: Any,
    dataset: Dataset,
    lines: Iterable[str],
    progress: Callable[[int], None] | None = None,
) -> IngestReport:
    stage_raw(connection, lines, progress)
    parse_staged(connection)
    counts = diagnose(connection)
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE {dataset.table} CASCADE")
        cursor.execute(dataset.insert_sql)
        inserted = cursor.rowcount
    return IngestReport(
        dataset=dataset.label,
        staged=counts["staged"],
        inserted=inserted,
        usable=counts["usable"],
        repaired=counts["repaired"],
        unparsable=counts["unparsable"],
        empty_after_repair=counts["empty_after_repair"],
        outside_poland=counts["outside_poland"],
    )


def match(
    connection: Any,
    min_share: float = MIN_MATCH_SHARE,
    min_record_inside: float = MIN_RECORD_INSIDE,
) -> MatchReport:
    """Zapisuje KAZDA przecinajaca sie pare, a regula decyduje tylko o liczniku dopasowan.

    Dzieki temu zmiana progu nie wymaga ponownego liczenia przeciec (2 minuty na pelnych danych),
    a pary odrzucone przez regule zostaja w bazie jako material dowodowy.
    """
    thresholds = {"min_share": min_share, "min_record_inside": min_record_inside}
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE building_registry_match")
        cursor.execute(MATCH)
        pairs = cursor.rowcount
        cursor.execute(COUNT_QUALIFYING_PAIRS, thresholds)
        qualifying = (cursor.fetchone() or [0])[0]
        cursor.execute(RESET_MATCH_COUNTS)
        cursor.execute(APPLY_MATCH_COUNTS, thresholds)
        buildings = cursor.rowcount
    return MatchReport(pairs=pairs, qualifying_pairs=qualifying, buildings_with_match=buildings)
