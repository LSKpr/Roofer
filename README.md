# Roofer

Roofer is an evidence-led map for exploring Polish asbestos registry records alongside OpenStreetMap building footprints and official GUGiK orthophotography. It does **not** classify roofs, make material predictions, or treat an unlisted building as clean.

## Quick start

Run this one command from the repository root:

```sh
docker compose up --build
```

Open `http://localhost:3000`. For non-default local values, copy `.env.example` to `.env` before starting and set a local PostgreSQL password. The API is available at `http://localhost:8000/api/v1/docs` and includes its generated OpenAPI contract.

Docker Compose starts PostgreSQL 16 with PostGIS, applies the Alembic migration before the API starts, and then starts the Next.js UI. Use `docker compose down` to stop it; add `-v` only when intentionally deleting the local database volume.

## Demo workflow

1. Search for a place or use the map around Warsaw.
2. Draw a rectangle or polygon no larger than the configured 25 km² limit.
3. Choose only a year that the UI lists as verified by the GUGiK coverage index.
4. Select **Analyze area**.
5. Inspect building status and evidence. Red means listed by GeoAzbest; teal means a cleaned/removal record; gray is *Not listed*; purple means ambiguous. None of these are laboratory confirmation.

`DEMO_FALLBACK_ENABLED=true` supplies three deterministic Warsaw fixture buildings only when Overpass or the GeoAzbest WFS is unavailable. Results show a fixture warning. Set it to `false` to exercise explicit `source_unavailable`/`unknown` handling instead.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `roofer` | Local database connection |
| `BUILDING_PROVIDER` | `overpass` | `overpass`, `local_postgis`, or deterministic `demo_fixture` |
| `DEMO_FALLBACK_ENABLED` | `true` | Enables clearly-labelled offline demo data |
| `MAX_ANALYSIS_AREA_KM2` | `25` | Server-enforced analysis-area cap |
| `NEXT_PUBLIC_API_BASE_URL` | `/api/v1` | Same-origin browser API path, proxied by Next.js to FastAPI |

## Verification

```sh
cd backend && python -m pip install -r requirements-dev.txt && pytest
cd ../frontend && npm install && npm run test && npm run build
```

PostGIS integration tests require a running PostGIS database through `DATABASE_URL`; unit tests do not call public services. See `docs/architecture.md` for API and deployment details.

## Important limitations

- GeoAzbest is a registry based on reported/inventoried material. A removal record can concern siding, pipes, stored material, or part of a building, not necessarily a roof.
- Registry absence is displayed as **Not listed**, never as clean or asbestos-free. Network failure produces **Unknown**.
- The application requests vector GeoAzbest WFS features; it never infers registry status from WMS pixels or colors.
- GUGiK historical imagery is offered only after the official index confirms coverage for the selected area. Comparison is historical context, not a roof-material conclusion.
- The application is designed for interactive viewport use and deliberately avoids bulk imagery harvesting.

See `docs/data-sources.md` for attribution, terms, and legal review requirements.
