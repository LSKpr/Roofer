# Project commands

- Start the complete application: `docker compose up --build`
- Backend unit tests: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
- Backend PostGIS integration test: set `POSTGIS_TEST_DATABASE_URL`, then run the backend tests.
- Frontend tests: `cd frontend && npm run test`
- Frontend type check: `cd frontend && npm run lint`
- Frontend production build: `cd frontend && npm run build`
- Browser E2E test: start the Docker stack with `BUILDING_PROVIDER=demo_fixture`, then run `cd frontend && npm run test:e2e`.

Use WFS vector features for GeoAzbest status, compute spatial metrics in EPSG:2180, and preserve the explicit `unknown` state on source failure.

# Roof image crops

- Install Python dependencies: `.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt` (Python 3.11+).
- Standalone roof crop: `.venv/Scripts/python.exe scripts/crop_roof.py --input roof.geojson --output output/roof`. Use `--input -` for UTF-8 GeoJSON on stdin; accept one WGS84 Polygon or Feature, not a FeatureCollection.
- Crop tests: `cd backend && ../.venv/Scripts/python.exe -m pytest -q tests/test_roof_crop.py`.
- Live download test: set `ROOF_CROP_LIVE_TEST=1`, then run `tests/test_roof_crop.py::test_live_original_geotiff_crop`. This downloads one real 2024 RGB sheet with a 128 MiB limit; ordinary tests do not contact GUGiK.
- The crop uses original RGB GeoTIFFs selected from the official resolution index (smallest native pixel, newest date as a tie-breaker). `--year` restricts acquisition year. WCS output pixel size alone does not establish native resolution or source provenance.
- Full originals are cached outside the repository in the OS user cache under `Roofer/orthophotos`; override with `--cache-dir`. Downloads are limited to 1536 MiB per original by default (`--max-download-mb`), and cached rasters are checksum-verified. PNG/JSON outputs never overwrite existing files.
- The 2022 paper (DOI `10.1016/j.buildenv.2022.109092`, sections 2.2 and 2.4) uses RGB 47x47 pixels at 0.25 m/pixel: an 11.75x11.75 m square. It discusses manually positioned roof centers; automatic polygon centroids are not an exact reproduction of that step. Do not mask surroundings or normalize each PNG independently.
- Centroids outside the roof require review. Crops crossing a selected sheet boundary or containing declared NoData fail explicitly; this version does not stitch sheets. The GUGiK index HTML parser must fail explicitly if its metadata format changes.
- The index also serves uppercase `.TIF` download URLs (2016 vintage). They are valid sources; rejecting them discards every record for that location, which removed 5% of surveyed cells.

# Labelled roof dataset

- Build: `.venv/Scripts/python.exe scripts/build_roof_dataset.py --registry Additional_data/geoazbest-mazowieckie.geojson/geoazbest-mazowieckie.geojson --buildings Additional_data/budynki-osm-mazowieckie.geojson/budynki-osm-mazowieckie.geojson --output dataset/pilot --positives 50 --negatives 200 --per-sheet-positives 10 --per-sheet-negatives 40 --max-sheets 8`. Add `--select-only` to stop after candidate selection; reruns resume from `manifest.jsonl` and never overwrite a crop.
- Dataset tests: `cd backend && ../.venv/Scripts/python.exe -m pytest -q tests/test_roof_dataset.py`.
- Positives are GeoAzbest polygons, negatives are OSM buildings at least `--exclusion-m` from every registry polygon, including registry polygons too broken to crop. Both classes come from the same sheets, so imagery date and sun angle cannot separate them.
- Pin `--year` and `--native-resolution`; a sheet without that exact native pixel is skipped, never substituted. 2024 at 0.25 m covers every dense cell at 36-46 MiB per sheet, while 0.05 m exists in 5-15% of cells at ~1.07 GiB per sheet, so the default smallest-pixel policy can neither cover the province uniformly nor fit on disk.
- Crop one sheet at a time. Per-crop CLI runs re-query the index and re-hash the whole cached original for every roof.
- Selection cells are 2 km squares and sheets are ~2.2x2.35 km with a different origin, so roughly 30% of candidates fall outside the downloaded sheet; selection keeps twice the per-sheet quota as spare.
- The snapshots are line-delimited with a `],"numberReturned":N}` footer; the reader verifies that count. Of 379122 registry records, 352101 are usable: 3393 do not project to EPSG:2180, 3402 fail crop validation, 1280 have a centroid outside the roof, 22339 fall outside the 20-1000 m2 range.
- GeoAzbest is a declaration register of asbestos remaining for disposal, with no dates in the public layer, describing asbestos in the structure rather than proven roofing. Absence from the register is not proof of a clean roof. Keep both statements in crop metadata.
