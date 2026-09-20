#!/usr/bin/env sh
set -eu

: "${OSM_PBF_PATH:?Set OSM_PBF_PATH to a manually downloaded Poland .osm.pbf file}"
: "${DATABASE_URL:?Set DATABASE_URL, for example postgresql://roofer:roofer@localhost:5432/roofer}"

osm2pgsql --create --slim --hstore --database "$DATABASE_URL" "$OSM_PBF_PATH"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "INSERT INTO local_osm_buildings (osm_type, osm_id, tags, geometry) SELECT 'way', osm_id, tags, ST_Transform(way::geometry, 4326), now() FROM planet_osm_polygon WHERE building IS NOT NULL ON CONFLICT (osm_type, osm_id) DO UPDATE SET tags = EXCLUDED.tags, geometry = EXCLUDED.geometry, source_updated_at = EXCLUDED.source_updated_at;"
