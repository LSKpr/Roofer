# Local OSM building provider

The default `overpass` provider is intended for small interactive analyses. `local_postgis` provides a future path for a locally maintained Poland extract without changing the analysis API.

## Obtain the extract

Download a current Poland `.osm.pbf` extract manually from [Geofabrik](https://download.geofabrik.de/europe/poland.html) or another source whose license and update terms you accept. The application never downloads a country extract during development or at startup.

## Import

Install `osm2pgsql` and PostgreSQL client tools on the import host. Start the database, then run:

```sh
export DATABASE_URL=postgresql://roofer:YOUR_PASSWORD@localhost:5432/roofer
export OSM_PBF_PATH=/absolute/path/to/poland-latest.osm.pbf
./scripts/import-osm-pbf.sh
```

The script imports the PBF through `osm2pgsql`, transforms `planet_osm_polygon.way` from the usual Web Mercator import CRS to EPSG:4326, and upserts building polygons into `local_osm_buildings`. For high-volume and repeatable imports, operate `osm2pgsql` with an explicit flex style that preserves way/relation IDs, tags, multipolygon topology, and source replication timestamps; then populate the same table contract.

Set `BUILDING_PROVIDER=local_postgis` in `.env` and restart the API. `LocalOsmBuildingProvider` queries native PostGIS geometry with a bounding-box prefilter and `ST_Intersects`.

## Schema contract

`local_osm_buildings` has `(osm_type, osm_id)` as a primary key, JSONB tags, native EPSG:4326 geometry, source update time, and a GiST index. For a production importer, retain relation geometry including interior rings; do not flatten multipolygons to exterior-only shapes.
