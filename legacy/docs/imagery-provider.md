# Imagery provider

`ImageryProvider` returns an `ImageryDescriptor` containing provider, layer ID, acquisition year, exact/ranged date metadata, resolution, coverage metadata, service configuration, attribution, and license notes. The first implementation is `GugikImageryProvider`.

## Availability

The GUGiK standard-resolution time WMS provides the historical map layer used by Roofer; high-resolution coverage is intentionally discontinuous and is not used as the nationwide basemap. A global time range does not prove a sheet covers a selected parcel. Roofer therefore checks an area bounding box against each relevant official `SkorowidzOrtofomapyYYYY` WFS layer before putting a year on the slider. If the index cannot be reached, no historical year is fabricated; the current verified WMS layer remains the only choice.

Each request is constrained and uses a concurrency limit of three index calls. Production deployments should cache index coverage by tile or administrative area with a TTL and track service capacity.

Tile delivery is deliberately conservative: the backend keeps one pooled HTTP client, limits upstream concurrency, retries transient failures, caches recent tiles in memory, and serves the nationwide standard-resolution service at wide zoom while preferring the high-resolution service from zoom 16. A tile that no official service can provide returns `source_unavailable`; the map then shows the base map rather than invented imagery.

## Rendering

MapLibre retains EPSG:3857 internals while the documented GUGiK WMS supports EPSG:2180/EPSG:4326. The backend provides small, cacheable viewport tile requests in EPSG:4326, preserving attribution. The map's building vector geometry is EPSG:4326 and remains spatially aligned at normal interactive zoom levels. The layer is visual evidence rather than a measurement surface.

The comparison modal displays two synchronized maps. A removal year creates an evidence prompt: years before it are labelled pre-removal context and years after it post-removal context. The wording deliberately says historical inference, not a guaranteed asbestos-roof label.

No Google imagery, undocumented tile endpoint, fabricated year, or placeholder aerial raster is used.
