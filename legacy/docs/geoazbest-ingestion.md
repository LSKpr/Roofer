# GeoAzbest WFS ingestion

## Discovery and validation

Before a sync, the backend can call `GetCapabilities` and `DescribeFeatureType` through `GET /api/v1/registry/capabilities`. It permits only the five layer names advertised by the service and never treats a WMS image as source data.

The feature mapper retains all original attributes in `registry_features.raw_properties`. It maps known `wyroby_dzialki` attributes including `id_lokalizacji`, `teryt`, `nr_dzialki`, urgency fields, planned/actual removal years, `ilosc_wyrobu`, and `ilosc_przekazana_do_unieszkodliwienia`. A missing or malformed value remains null rather than becoming zero or false.

## Scopes

`POST /api/v1/registry/sync` accepts exactly one selected layer and one of:

- `bbox: [minLon, minLat, maxLon, maxLat]`
- numeric `teryt`
- `full_country: true`

Each scope is hashed with its layer. That scope key identifies a `RegistrySyncCheckpoint`, allowing an interrupted request to resume from its recorded `next_start_index`.

## Pagination, retry, and progress

Requests use WFS 2.0 parameters `outputFormat=json`, `startIndex`, `count`, and `srsName=EPSG:4326`; a validated bbox or CQL `teryt` filter narrows a scope. The service's WFS capabilities advertise paging support. The importer reads `numberReturned`/`numberMatched`, advances the checkpoint after every committed page, retries transient errors four times with exponential backoff, and records `source_unavailable` on final failure.

Every source feature is upserted on `(geoazbest_layer, source_feature_id)`, enabling repeated runs without duplicate records. Each upsert refreshes `synchronized_at` and preserves current raw source properties for reproducibility.

## Matching

The analysis retrieves registry layers once per selected area, then performs matching locally. Candidates are preserved, not collapsed. The sequence is:

1. Match a location identifier when an OSM tag carries one.
2. Match parcel number when available.
3. Require physical intersection as validation.
4. Calculate intersection area and building overlap in EPSG:2180.
5. Attach every candidate and mark close competing scores ambiguous.

A building may receive multiple matches. Listed plus cleaned evidence is purple/ambiguous. A registry source failure produces `unknown`; it never produces `not_listed`.
