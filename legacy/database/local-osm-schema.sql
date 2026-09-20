CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS local_osm_buildings (
  osm_type text NOT NULL,
  osm_id bigint NOT NULL,
  tags jsonb NOT NULL DEFAULT '{}'::jsonb,
  geometry geometry(GEOMETRY, 4326) NOT NULL,
  source_updated_at timestamptz,
  imported_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (osm_type, osm_id)
);

CREATE INDEX IF NOT EXISTS local_osm_buildings_geometry_gix ON local_osm_buildings USING gist (geometry);
