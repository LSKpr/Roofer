-- P1: budynki OSM, rekordy rejestru GeoAzbest i ich dopasowanie.

-- ST_GeomFromGeoJSON przerywa cale zapytanie na jednym zepsutym obiekcie. Snapshoty maja
-- kilka tysiecy takich rekordow, wiec zamieniamy blad na NULL. Liczba odrzuconych obiektow
-- jest raportowana przez ingest, nie ukrywana.
CREATE OR REPLACE FUNCTION safe_geojson_geometry(payload text) RETURNS geometry
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
BEGIN
    RETURN ST_SetSRID(ST_GeomFromGeoJSON(payload), 4326);
EXCEPTION
    WHEN others THEN RETURN NULL;
END;
$$;

CREATE TABLE osm_buildings (
    id               bigserial PRIMARY KEY,
    osm_id           text,
    fclass           text,
    name             text,
    geom             geometry(MultiPolygon, 4326) NOT NULL,
    centroid         geometry(Point, 4326)        NOT NULL,
    area_m2          double precision             NOT NULL,
    repaired         boolean NOT NULL DEFAULT false,
    registry_matches integer NOT NULL DEFAULT 0
);

CREATE INDEX osm_buildings_geom_gix ON osm_buildings USING gist (geom);
CREATE INDEX osm_buildings_centroid_gix ON osm_buildings USING gist (centroid);
CREATE INDEX osm_buildings_matches_idx ON osm_buildings (registry_matches);

-- Rejestr zgloszen, nie dowod pokrycia dachu. Wszystkie atrybuty zrodlowe zostaja w properties.
CREATE TABLE registry_records (
    id         bigserial PRIMARY KEY,
    source_id  text,
    nr_dzialki text,
    properties jsonb NOT NULL DEFAULT '{}'::jsonb,
    geom       geometry(MultiPolygon, 4326) NOT NULL,
    centroid   geometry(Point, 4326)        NOT NULL,
    area_m2    double precision             NOT NULL,
    repaired   boolean NOT NULL DEFAULT false
);

CREATE INDEX registry_records_geom_gix ON registry_records USING gist (geom);
CREATE INDEX registry_records_source_idx ON registry_records (source_id);

-- Kazda para przecinajacych sie obiektow, z obydwoma udzialami powierzchni. Kandydatow nie
-- scalamy: jeden budynek moze miec kilka rekordow i to jest informacja, nie blad.
CREATE TABLE building_registry_match (
    building_id    bigint NOT NULL REFERENCES osm_buildings(id) ON DELETE CASCADE,
    record_id      bigint NOT NULL REFERENCES registry_records(id) ON DELETE CASCADE,
    overlap_m2     double precision NOT NULL,
    share_building double precision NOT NULL,
    share_record   double precision NOT NULL,
    PRIMARY KEY (building_id, record_id)
);

CREATE INDEX building_registry_match_record_idx ON building_registry_match (record_id);
