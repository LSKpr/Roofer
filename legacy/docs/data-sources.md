# Data sources, attribution, and limitations

## GeoAzbest / Baza Azbestowa

- **Provider:** Baza Azbestowa, described by the site as maintained by Poland's Ministry of Development and Technology.
- **Service:** `https://esip.bazaazbestowa.gov.pl/geoserver/wfs/ows`
- **Use:** vector WFS only, via `GetCapabilities`, `DescribeFeatureType`, and `GetFeature?outputFormat=json`. The provider describes WFS as returning features, geometry, and attributes for spatial analyses; WMS is explicitly only a rendered map service.
- **Layers validated from WFS capabilities:** `wfs:budynki_z_azbestem`, `wfs:budynki_oczyszczone`, `wfs:budynki`, `wfs:wyroby_dzialki`, and `wfs:wyroby_rury`.
- **Advertised CRS:** EPSG:2180, with Poland-wide extent. Roofer requests EPSG:4326 for map delivery and uses EPSG:2180 for measurements.
- **Attribution:** `GeoAzbest / Baza Azbestowa` with the source layer and synchronization time shown in evidence.

The public OGC page establishes access but does **not** state in the material verified for this project that unrestricted redistribution is permitted. This application retains provenance, provides attribution, and does not claim any unrestricted redistribution right. Confirm current provider terms, personal-data implications, and intended commercial use with the source owner before deployment.

Registry records are reported inventory/removal information. They are not laboratory results and might describe non-roof asbestos products. `wyroby_dzialki` is parcel-level: a parcel can contain several buildings and records, so it is never assumed to identify one roof.

## OpenStreetMap and Overpass

- **Default building provider:** Overpass API at `https://overpass-api.de/api/interpreter`.
- **Use:** on-demand building ways and relations inside the selected bounding box. The application retains source type/ID, tags, polygon/multipolygon geometry, and any available source timestamp.
- **Attribution:** © OpenStreetMap contributors. Comply with the current ODbL and attribution requirements for deployed use.
- **Limitations:** OSM completeness, topology, and timestamps vary. An OSM building is not cadastral evidence.

## GUGiK / Geoportal orthophotography

- **Provider:** Główny Urząd Geodezji i Kartografii (GUGiK), Geoportal.gov.pl.
- **Current nationwide standard-resolution WMS:** `https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution`, technical layer name `Raster`.
- **Historical standard-resolution time WMS:** `https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolutionTime`, technical layer name `Raster`; available years are still verified against the official index before display.
- **High-resolution services:** `.../WMS/HighResolution` and `.../WMS/HighResolutionTime`, technical layer name `Raster`. Their coverage is intentionally discontinuous, so they are never used for country-scale view. From zoom 16 upward the backend requests the high-resolution service first and falls back to the nationwide standard-resolution service, so a rendered tile is always real official imagery and a missing tile is reported as `source_unavailable` instead of being faked.
- **Official index WFS:** `https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WFS/Skorowidze`; capability records expose year-specific `gugik:SkorowidzOrtofomapyYYYY` layers, including historic years.
- **CRS:** capability documents advertise EPSG:2180 and EPSG:4326. MapLibre uses Web Mercator, so Roofer's backend creates small WMS request tiles in EPSG:4326 for the live viewport; this is an interactive visual layer, not a downloadable imagery product.
- **Attribution:** `Orthophotomap: GUGiK / Geoportal.gov.pl` is shown by the map.

The checked current WMTS service states that use is free and prohibits automated harvesting of imagery/feature-info content while permitting derived information. The Geoportal terms page also contains broader legacy-use restrictions. Those texts must be reviewed against the exact production access method and deployment jurisdiction. Roofer does not cache full imagery, scrape undocumented providers, or use Google Satellite endpoints.

## Geocoding

Search uses the public Nominatim endpoint with a descriptive User-Agent, a small result limit, and user-initiated queries. A production deployment should use a compliant hosted Nominatim service or another licensed geocoder at its expected traffic level.
