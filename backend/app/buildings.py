"""Szczegoly jednego budynku razem z dopasowanymi rekordami rejestru."""

from typing import Any

from app.ingest import MATCH_RULE, MIN_MATCH_SHARE, MIN_RECORD_INSIDE

BUILDING_SQL = f"""
SELECT b.id,
       b.osm_id,
       b.fclass,
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
WHERE b.id = %(id)s
"""


async def read_building(pool: Any, building_id: int, timeout: float) -> dict[str, Any] | None:
    parameters = {
        "id": building_id,
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
