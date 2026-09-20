"""Szczegoly jednego budynku razem z dopasowanymi rekordami rejestru.

Budynek adresujemy przez `osm_id`, bo klucz `id` z sekwencji nie przezywa ponownego importu
(TRUNCATE nie zeruje sekwencji — pulapka 21 w AGENTS.md) i zapisany adres przestawal dzialac.
Wewnatrz zapytania `id` zostaje: po nim lacza sie tabele (`building_registry_match.building_id`),
a publicznym identyfikatorem w odpowiedzi jest `osm_id` pod nazwa `id`.
"""

from typing import Any

from app.ingest import MATCH_RULE, MIN_MATCH_SHARE, MIN_RECORD_INSIDE

# `osm_id = %(id)s::text`, a nie `osm_id::bigint = %(id)s`: rzutowanie kolumny wyklucza indeks
# osm_buildings_osm_id_key (migracja 006) i zapytanie schodzi na Parallel Seq Scan po 1,2 GB tabeli
# (zmierzone: 264 ms wobec 0,5 ms na Index Scan). Rzutujemy wiec parametr, ktory przychodzi jako
# liczba calkowita z walidacji FastAPI.
#
# W odpowiedzi jest jedno `id` i jest nim `osm_id::bigint` — osobne pole `osmId` byloby ta sama
# liczba w dwoch typach, czyli zaproszeniem do pomylki, ktory z nich jest adresem budynku.
BUILDING_SQL = f"""
SELECT b.osm_id::bigint AS id,
       b.fclass,
       b.osm_type,
       b.name,
       round(b.area_m2::numeric, 1)::float8 AS area_m2,
       ST_X(b.centroid)  AS lng,
       ST_Y(b.centroid)  AS lat,
       b.registry_matches,
       coalesce((
           SELECT json_agg(json_build_object(
                      'sourceId',      r.source_id,
                      'nrDzialki',     r.nr_dzialki,
                      'recordAreaM2',  round(r.area_m2::numeric, 1)::float8,
                      'overlapM2',     round(m.overlap_m2::numeric, 1)::float8,
                      'shareBuilding', round(m.share_building::numeric, 3)::float8,
                      'shareRecord',   round(m.share_record::numeric, 3)::float8
                  ) ORDER BY m.overlap_m2 DESC)
           FROM building_registry_match m
           JOIN registry_records r ON r.id = m.record_id
           WHERE m.building_id = b.id AND {MATCH_RULE}
       ), '[]'::json) AS records,
       (
           SELECT count(*)
           FROM building_registry_match m
           WHERE m.building_id = b.id AND NOT ({MATCH_RULE})
       ) AS other_intersecting
FROM osm_buildings b
WHERE b.osm_id = %(id)s::text
"""


async def read_building(pool: Any, osm_id: int, timeout: float) -> dict[str, Any] | None:
    parameters = {
        "id": osm_id,
        "min_share": MIN_MATCH_SHARE,
        "min_record_inside": MIN_RECORD_INSIDE,
    }
    async with pool.connection(timeout=timeout) as connection:
        cursor = await connection.execute(BUILDING_SQL, parameters)
        row = await cursor.fetchone()
        names = [column.name for column in cursor.description or []]
    if row is None:
        return None
    return dict(zip(names, row, strict=True))
