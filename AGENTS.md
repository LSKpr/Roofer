# Active build

`PROJECT.md` is the binding brief for the current work on `frontendv2`: a pnpm monorepo with an
Express/Prisma/MySQL backend, a Next.js + Leaflet frontend, and a FastAPI/ONNX ML service. Build it
phase by phase in the order given in section 10; do not start a phase that was not named, and do not
change the stack in section 3 without asking.

F0 is done: pnpm workspace with `packages/{database,validation,backend,frontend}`, shared
`tsconfig.base.json`, flat ESLint config, `docker-compose.yml` with MySQL 8.4, `.env.example`.
The packages are scaffolding; their `src/index.ts` files are empty on purpose.

- Install: `pnpm install`
- Build every package: `pnpm build`
- Type check (source and tests): `pnpm typecheck`
- Run tests: `pnpm test`
- Lint: `pnpm lint`
- Database: `pnpm docker:up` / `pnpm docker:down` (MySQL on `localhost:3306`, user/password/db all `roofer`)

Write tests as you go and keep the units under test small and directly checkable; that is an
explicit instruction from the project owner, not a style preference.

Push to `origin` often, without being asked each time: after every phase and after every
self-contained step within one. Work is on the `frontendv2` branch. Commit only with the working
tree verified green (`pnpm build`, `pnpm typecheck`, `pnpm test`, `pnpm lint`), so that what lands
on the remote is always in a state someone else could pull.

## Testing

The runner is Node's built-in `node:test` with `node:assert/strict`. There is no Vitest or Jest.
Tests live in `packages/<pkg>/tests/**/*.test.ts(x)` and are run through the `tsx` CLI.

- `node:test` cannot transform JSX and has no DOM. React component tests work only because
  `tsx --tsconfig tsconfig.test.json` supplies the JSX transform and `tests/setup.ts` installs a
  jsdom window onto `globalThis`. Do not drop either.
- Each package has a `tsconfig.test.json` because the build config sets `rootDir: src` and would
  refuse to see `tests/`. `typecheck` runs against the test config, so type errors in tests fail
  the build. Verified by planting a deliberate error.
- pnpm runs scripts through `cmd.exe` on Windows, so `VAR=value cmd` in a `scripts` entry does not
  work. Pass configuration as a CLI flag instead of an environment variable.
- jsdom 30 ships no type declarations; `@types/jsdom` is a separate dependency.
- For backend HTTP tests, start the Express app on an ephemeral port and use the global `fetch`.
  Do not add supertest.

Version constraints found by running the toolchain, not by guessing:

- pnpm is pinned to 11.27.0. pnpm 12 is a Rust rewrite whose native binary the Node 22 corepack
  (0.31) cannot install, so `corepack pnpm` fails outright on it.
- pnpm 11 removed `onlyBuiltDependencies`; build approval lives in `allowBuilds` in
  `pnpm-workspace.yaml`. The old key is silently ignored and the install fails with
  `ERR_PNPM_IGNORED_BUILDS`.
- TypeScript is pinned to 6.0.3. TS 7.0 compiles and builds fine, but typescript-eslint 8.70
  refuses to load against it, so linting is impossible on TS 7.
- `pnpm` reaches PATH through a corepack shim in `%APPDATA%\npm`; `corepack enable` without
  `--install-directory` needs administrator rights on this machine.
- Docker Desktop is installed but not on PATH in a plain shell. Prefix with
  `export PATH="$PATH:/c/Program Files/Docker/Docker/resources/bin"` when needed.

Decisions that override the legacy prototype:

- Asbestos registry status comes from the WMS pixel probe described in `PROJECT.md` section 7.2, not
  from WFS vector features. That reverses the earlier rule and is a deliberate choice; the pixel
  probe is less precise and returns no record attributes.
- The ML prediction service is deferred. Keep `isPotentiallyAsbestos` nullable and leave it `null`
  rather than writing `false` for an unchecked building.

# Legacy prototype (`legacy/`)

The FastAPI + PostGIS + MapLibre application that preceded this rebuild. It is kept for reference and
for the roof-crop and dataset tooling, which the new stack does not replace. Leave it working.

- Start it: `docker compose -f legacy/docker-compose.yml up --build`
- Backend unit tests: `cd legacy/backend && ../../.venv/Scripts/python.exe -m pytest -q`
- Backend PostGIS integration test: set `POSTGIS_TEST_DATABASE_URL`, then run the backend tests.
- Frontend tests: `cd legacy/frontend && npm run test`
- Frontend type check: `cd legacy/frontend && npm run lint`
- Frontend production build: `cd legacy/frontend && npm run build`
- Browser E2E test: start the legacy stack with `BUILDING_PROVIDER=demo_fixture`, then run `cd legacy/frontend && npm run test:e2e`.

The legacy backend uses WFS vector features for GeoAzbest status, computes spatial metrics in
EPSG:2180, and preserves the explicit `unknown` state on source failure. Do not retrofit the new
WMS decision into it.

# Roof image crops

- Install Python dependencies: `.venv/Scripts/python.exe -m pip install -r legacy/backend/requirements-dev.txt` (Python 3.11+).
- Standalone roof crop: `.venv/Scripts/python.exe legacy/scripts/crop_roof.py --input roof.geojson --output output/roof`. Use `--input -` for UTF-8 GeoJSON on stdin; accept one WGS84 Polygon or Feature, not a FeatureCollection.
- Crop tests: `cd legacy/backend && ../../.venv/Scripts/python.exe -m pytest -q tests/test_roof_crop.py`.
- Live download test: set `ROOF_CROP_LIVE_TEST=1`, then run `tests/test_roof_crop.py::test_live_original_geotiff_crop`. This downloads one real 2024 RGB sheet with a 128 MiB limit; ordinary tests do not contact GUGiK.
- The crop uses original RGB GeoTIFFs selected from the official resolution index (smallest native pixel, newest date as a tie-breaker). `--year` restricts acquisition year. WCS output pixel size alone does not establish native resolution or source provenance.
- Full originals are cached outside the repository in the OS user cache under `Roofer/orthophotos`; override with `--cache-dir`. Downloads are limited to 1536 MiB per original by default (`--max-download-mb`), and cached rasters are checksum-verified. PNG/JSON outputs never overwrite existing files.
- The 2022 paper (DOI `10.1016/j.buildenv.2022.109092`, sections 2.2 and 2.4) uses RGB 47x47 pixels at 0.25 m/pixel: an 11.75x11.75 m square. It discusses manually positioned roof centers; automatic polygon centroids are not an exact reproduction of that step. Do not mask surroundings or normalize each PNG independently.
- Centroids outside the roof require review. Crops crossing a selected sheet boundary or containing declared NoData fail explicitly; this version does not stitch sheets. The GUGiK index HTML parser must fail explicitly if its metadata format changes.
- The index also serves uppercase `.TIF` download URLs (2016 vintage). They are valid sources; rejecting them discards every record for that location, which removed 5% of surveyed cells.

# Labelled roof dataset

- Build: `.venv/Scripts/python.exe legacy/scripts/build_roof_dataset.py --registry Additional_data/geoazbest-mazowieckie.geojson/geoazbest-mazowieckie.geojson --buildings Additional_data/budynki-osm-mazowieckie.geojson/budynki-osm-mazowieckie.geojson --output dataset/pilot --positives 50 --negatives 200 --per-sheet-positives 10 --per-sheet-negatives 40 --max-sheets 8`. Add `--select-only` to stop after candidate selection; reruns resume from `manifest.jsonl` and never overwrite a crop.
- Dataset tests: `cd legacy/backend && ../../.venv/Scripts/python.exe -m pytest -q tests/test_roof_dataset.py`.
- Positives are GeoAzbest polygons, negatives are OSM buildings at least `--exclusion-m` from every registry polygon, including registry polygons too broken to crop. Both classes come from the same sheets, so imagery date and sun angle cannot separate them.
- Pin `--year` and `--native-resolution`; a sheet without that exact native pixel is skipped, never substituted. 2024 at 0.25 m covers every dense cell at 36-46 MiB per sheet, while 0.05 m exists in 5-15% of cells at ~1.07 GiB per sheet, so the default smallest-pixel policy can neither cover the province uniformly nor fit on disk.
- Crop one sheet at a time. Per-crop CLI runs re-query the index and re-hash the whole cached original for every roof.
- Selection cells are 2 km squares and sheets are ~2.2x2.35 km with a different origin, so roughly 30% of candidates fall outside the downloaded sheet; selection keeps twice the per-sheet quota as spare.
- The snapshots are line-delimited with a `],"numberReturned":N}` footer; the reader verifies that count. Of 379122 registry records, 352101 are usable: 3393 do not project to EPSG:2180, 3402 fail crop validation, 1280 have a centroid outside the roof, 22339 fall outside the 20-1000 m2 range.
- GeoAzbest is a declaration register of asbestos remaining for disposal, with no dates in the public layer, describing asbestos in the structure rather than proven roofing. Absence from the register is not proof of a clean roof. Keep both statements in crop metadata.

`Additional_data/` and `dataset/` stay at the repository root; the tooling that reads them moved, the
data did not.
