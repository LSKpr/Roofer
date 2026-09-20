# Roofer

Find roofs that look like asbestos cement but are missing from the official register.

Roofer puts three independent sources on one map for the Masovian Voivodeship in Poland: **2,585,219
OpenStreetMap buildings**, **379,011 records from the GeoAzbest asbestos register**, and a **machine
learning model** that scores how much a roof looks like corrugated grey cement sheets. Select an
area and the app tells you how many roofs the model flags that nobody has reported, and lists them
one by one with an aerial photo of each.

The register is the legal record. The model is a hint. The app never mixes the two up.

## What it does

- **Map of every building** in the voivodeship, coloured by register status, served as vector tiles.
  Below zoom 14 it switches to a density grid, because 319,869 individual points is 815 KB per tile.
- **Area scan.** Draw a rectangle: how many buildings, how many are in the register, total roof area,
  and the list of registered buildings with their parcel numbers.
- **Model analysis of a whole area.** The area is split into chunks that fit the model's limits and
  analysed one by one, with results appearing as they arrive.
- **The list that matters:** roofs above your chosen threshold that are *not* in the register,
  sorted by score, each with a real orthophoto crop, clickable straight to the building card.
- **Threshold slider** with a histogram of the score distribution. Moving it recalculates every
  number in the browser and never calls the model again.
- **Building card:** OSM type, area, matching register records with overlap shares, an aerial crop,
  and the model score with what it does and does not mean.

## Honesty rules

These are enforced by tests, not by good intentions.

- **Three states, never two.** A building is in the register, not in the register, or unknown to us.
  A roof is flagged, not flagged, or has no score. "No result" is never displayed as zero.
- **Missing from the register is not a clean roof.** It means nobody reported it. The register is
  incomplete.
- **A score below the threshold is not proof of anything.** The threshold is the analyst's decision.
  The model's author reports 77% accuracy and 63% asbestos recall.
- **Register facts and model guesses stay visually separate.** Red fill means the building is in the
  register. An orange outline means the model flagged it. A grey building with an orange outline is
  the interesting case.
- **The model looks at a different photo than you do.** It scores Google Satellite at zoom 20; the
  card shows GUGiK orthophoto. Every note says so.
- **Nothing is green.** Green would read as "safe", and we never know that.

## Architecture

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | Vite, React, TypeScript, Tailwind 4, MapLibre GL | the backend is separate, so SSR buys nothing; MapLibre is required for MVT tiles |
| Backend | FastAPI, psycopg, raw SQL | the whole value is `ST_Intersects`, `ST_AsMVT`, `ST_Area(geography)`; an ORM does not wrap that |
| Database | PostgreSQL 16 + PostGIS in Docker | 2.6M polygons need GiST indexes |
| Model | ONNX service run locally | the author's preprocessing is not a detail; we run his code rather than reimplement it |

### How the datasets are joined

The register has **no building identifier** — only a parcel number and a shape. So the join is
spatial: every intersecting pair is stored with its overlap area, and a rule decides which pairs
count. The rule exists because some register geometries are parcel outlines rather than roofs (the
largest is 73.7 km², the median is 99 m²); without it, one record would mark every shed around it.

```
match counts when  min(share_of_building, share_of_record) >= 0.10
                or share_of_record >= 0.50
```

419,321 intersecting pairs, 334,310 qualifying, **319,869 buildings with a match (12.4%)**. Rejected
pairs stay in the database, so a building card can say "this also touches N records that failed our
rule" instead of hiding the decision.

The model is joined by `osm_id` instead, because it was built from the same OSM snapshot. Matching by
identifier avoids picking the neighbour's garage out of a shared bounding box.

## Running it

Ports: **5173** frontend, **8001** backend, **5433** Postgres, **8020** model service.

```bash
# database
docker compose up -d

# backend (from backend/, venv is backend/.venv, Python 3.11)
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m scripts.migrate
.venv/Scripts/python.exe -m scripts.ingest --registry <registry.geojson> --buildings <buildings.geojson>
.venv/Scripts/python.exe -m scripts.serve --watch

# frontend (from frontend/)
pnpm install
pnpm dev
```

One `.env` in the repository root serves both processes: the backend reads `../.env`, Vite uses
`envDir: '..'`. See `.env.example` for every setting. The import takes about 6 minutes on full data
and the database ends up around 1.4 GB.

**Data is not in the repository.** The OSM and register snapshots, and the 801 exported roof crops,
live outside the working tree. Paths are configured through `.env`.

### Tests

```bash
cd backend  && .venv/Scripts/python.exe -m pytest     # 414 tests
cd frontend && pnpm test && pnpm typecheck && pnpm lint && pnpm build   # 528 tests
```

## HTTP API

Everything is under `/api`. The frontend calls relative paths and Vite proxies them, so CORS does not
depend on which address the page was opened from.

| Route | What it does |
| --- | --- |
| `GET /api/health` | database and PostGIS state |
| `GET /api/tiles/buildings/{z}/{x}/{y}.mvt` | vector tiles: outlines from zoom 14, density grid at 8 to 13 |
| `GET /api/buildings/{osm_id}` | building, register records, and which roof photo we have |
| `GET /api/buildings/{osm_id}/analysis` | model score, or an explicit "no result" |
| `GET /api/buildings/{osm_id}/roof.png` | aerial crop, from disk when we have one, otherwise from the WMS |
| `POST /api/area/scan` | register statistics for a rectangle |
| `POST /api/area/plan` | splits a rectangle into chunks the model will accept |
| `POST /api/area/analyze` | runs the model over one chunk and joins the result to the register |
| `GET /api/area/limits` | area limits, so the frontend does not keep its own copy |
| `GET /api/villages` | villages whose roof crops are cached on disk |
| `GET /api/imagery/orthophoto/{z}/{x}/{y}.png` | GUGiK WMS proxy in EPSG:3857 |
| `GET /api/geocode?q=` | Nominatim proxy, rate limited and cached |

## Data sources and terms

- **Buildings:** OpenStreetMap via Geofabrik, ODbL.
- **Register:** GeoAzbest public layer, Masovian Voivodeship.
- **Imagery:** GUGiK / Geoportal.gov.pl. Their terms exclude automated downloading and collecting of
  images, so the app only fetches what a user is looking at and caches it in memory. There is no
  bulk download anywhere in this repository.
- **Model imagery:** Google Satellite, fetched by the model service.

## Notes

`AGENTS.md` holds the working notes: measurements, traps confirmed by running things rather than
guessing, and the reasoning behind decisions that look arbitrary. Read it before changing anything
about tiles, caching, or the matching rule.
