# Roofer

Mapa z rejestrem azbestu i budynkami OSM dla województwa mazowieckiego, plus dwa narzędzia:
**skan obszaru** (prostokąt → lista budynków i statystyki) i **karta budynku** (rekord rejestru,
powierzchnia, wycinek ortofoto). Model ML dostarczy zewnętrzne API: wysyłamy narożniki prostokąta,
dostajemy poligony z pozycją na mapie — do połączenia z budynkami przez `ST_Intersects`.

Branch `v3` zaczyna się od zera, decyzją właściciela projektu z 2026-09-20. Wcześniejsze pliki
planu (`PROJECT.md`, `PHASES.md`, `STATUS.md`) i monorepo TS **nie obowiązują** — są na branchu
`frontendv2`.

## Stack

| Warstwa | Wybór | Dlaczego tak |
| --- | --- | --- |
| Frontend | Vite + React + TS + Tailwind 4 + MapLibre GL | backend jest osobny, więc SSR Next.js nic nie kupuje; MapLibre jest wymagany przy kaflach MVT |
| Backend | FastAPI + psycopg, surowy SQL bez ORM | cała wartość to `ST_Intersects`, `ST_AsMVT`, `ST_Area(geography)` — ORM tego nie opakowuje |
| Baza | Postgres 16 + PostGIS w Dockerze | 2,58 mln poligonów OSM i 379 tys. rekordów rejestru wymagają GiST |
| Migracje | pliki `db/migrations/*.sql` + `backend/scripts/migrate.py` | z sumą kontrolną: edycja zastosowanego pliku to błąd, nie ostrzeżenie |
| Rendering budynków | kafle wektorowe `ST_AsMVT` | Leaflet z SVG dławi się przy kilku tysiącach wielokątów |

## Porty

5173 frontend, 8001 backend, 5433 Postgres. Porty 3000, 8000, 5432 i 3306 zajmują sieroce
kontenery starego stacku z projektu compose `roofer`; nowy projekt nazywa się `roofer-v3`
i świadomie ich nie rusza.

## Komendy

Docker nie jest w PATH w zwykłej powłoce: `export PATH="$PATH:/c/Program Files/Docker/Docker/resources/bin"`.

- Baza: `docker compose up -d` / `docker compose down` (wolumen `roofer-v3_pgdata`)
- Backend (z katalogu `backend/`, venv to `backend/.venv`, Python 3.11.9):
  - instalacja: `.venv/Scripts/python.exe -m pip install -r requirements-dev.txt`
  - migracje: `.venv/Scripts/python.exe -m scripts.migrate`
  - serwer dev: `.venv/Scripts/python.exe -m scripts.serve`
  - testy: `.venv/Scripts/python.exe -m pytest`
  - testy z prawdziwą bazą: ustaw `TEST_DATABASE_URL=postgresql://roofer:roofer@localhost:5433/roofer`
  - lint: `.venv/Scripts/python.exe -m ruff check .` oraz `... -m ruff format --check .`
- Frontend (z katalogu `frontend/`): `pnpm install`, `pnpm dev`, `pnpm test`, `pnpm typecheck`,
  `pnpm lint`, `pnpm build`

Jeden `.env` w katalogu głównym obsługuje oba procesy: backend czyta `../.env`, Vite ma `envDir: '..'`.

## Fazy

| Faza | Zakres | Gotowe, gdy | Stan |
| --- | --- | --- | --- |
| P0 | Szkielet: PostGIS, FastAPI `/health`, mapa MapLibre, testy | mapa renderuje się w przeglądarce, `/health` zwraca wersję PostGIS | gotowe 2026-09-20 |
| P1 | Import snapshotów, tabele, dopasowanie budynek↔rejestr | liczby zgadzają się ze stopkami snapshotów, zapytanie o bbox 2×2 km poniżej 100 ms | — |
| P2 | Kafle wektorowe `/tiles/buildings/{z}/{x}/{y}.mvt` + kolorowanie | całe województwo przewija się płynnie | — |
| P3 | Skan obszaru: rysowanie prostokąta, lista, statystyki | liczby w panelu zgadzają się z mapą | — |
| P4 | Karta budynku: atrybuty rejestru, powierzchnia, ortofoto | klik w zgłoszony budynek pokazuje atrybuty i zdjęcie dachu | — |
| P5 | Gniazdo na API ML | podmiana jednej zmiennej środowiskowej wpina serwis kolegi | — |

Nie zaczynaj fazy, której właściciel nie nazwał.

## Pułapki potwierdzone uruchomieniem, nie domysłem

1. **psycopg async nie działa na `ProactorEventLoop`**, domyślnej pętli asyncio na Windowsie —
   `pool.open()` wisi 30 s i kończy się `PoolTimeout`. Fabryka pętli jest w `app/eventloop.py`,
   uvicorn dostaje ją przez `--loop app.eventloop:new_event_loop` (uvicorn 0.52 przyjmuje własną
   fabrykę jako `moduł:funkcja`), a pytest przez hook `pytest_asyncio_loop_factories`
   w `tests/conftest.py`. Nadpisywanie fixture'a `event_loop_policy` jest w pytest-asyncio 1.4
   **deprecated** — nie wracaj do niego.
2. **Skrypty uruchamiaj jako moduł.** `python scripts/migrate.py` nie widzi paczki `app`;
   działa `python -m scripts.migrate`.
3. **pnpm 11 bez TTY** przerywa czyszczenie `node_modules`
   (`ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`). Potrzebne `CI=true`, a wtedy install jest
   frozen — dorzuć `--no-frozen-lockfile`, jeśli zmieniałeś `package.json`.
4. **Wersje pinujemy na sztywno i tylko takie, które mają ponad tydzień.** Dlatego oxlint 1.82.0
   (nie 1.83.0), vitest 5.0.0, maplibre-gl 6.9.0, jsdom 30.0.1, uvicorn 0.52.4, psycopg 3.3.5,
   ruff 0.16.7. `@types/node` to 22.20.2, bo lokalny Node to 22.14 — generator Vite proponował 24.x.
5. **Nie ma GDAL-a, `ogr2ogr` ani geopandas**, są `shapely`, `pyproj` i `psycopg`. Import w P1 musi
   czytać snapshoty linia po linii (jeden feature na linię, w stopce `],"numberReturned":N}`
   — sprawdzaj tę liczbę) i ładować przez `COPY`. `INSERT` per feature to godziny przy 2,58 mln rekordów.
6. **GUGiK udostępnia tu WMS, nie WMTS**: `mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/`
   `StandardResolution`, `HighResolution` i warianty `*Time`, plus WFS `Skorowidze` jako indeks
   pokrycia. Do wycinka jednego dachu `GetMap` z dowolnym bboxem jest właściwym narzędziem;
   WMTS wymagałby zszywania kafli siatki.
7. **Starlette sugeruje `httpx2` dla `TestClient`** — wersja 2.13.0 ma 6 dni, więc zostajemy na
   httpx 0.28.1 i świadomie akceptujemy to ostrzeżenie.
8. **Vite 8 generuje `oxlint`**, nie ESLinta. Zostawiamy oxlint.
9. **Bundle ma 1,24 MB** (prawie w całości MapLibre). Code splitting dopiero, gdy będzie miało sens.
10. **Kafle OSM (`tile.openstreetmap.org`) są dobre na development.** Publiczne demo potrzebuje
    własnego źródła; atrybucja jest wymagana i pilnuje jej test `basemap.test.ts`.

## Dane

`Additional_data/DATA_MAZOWIECKIE.md` opisuje pochodzenie, licencje i liczebność snapshotów.
Same pliki (0,9 GB budynków OSM, 118 MB rejestru) leżą na dysku nieśledzone przez Gita.

GeoAzbest to **rejestr zgłoszeń** wyrobów azbestowych pozostałych do unieszkodliwienia, bez dat
w warstwie publicznej, i opisuje azbest w obiekcie, nie udowodnione pokrycie dachu. Brak w rejestrze
nie jest dowodem czystego dachu. W UI mów „zgłoszony” / „niezgłoszony” / „nieznany” — nigdy
„wykryto azbest”. Status nieznany zapisujemy jako `null`, nigdy jako `false`.

## Konwencje

- Testy piszemy razem z kodem, jednostki małe i sprawdzalne bezpośrednio. To polecenie właściciela.
- Komunikaty dla użytkownika po polsku i konkretne.
- Push do `origin` po każdej fazie i po każdym samodzielnym kroku, bez pytania — ale tylko
  z zielonym drzewem (backend: ruff + pytest, frontend: typecheck + test + lint + build).
- Każde zewnętrzne źródło ma stan „nieznany”; padnięte API nie może wywalić całej odpowiedzi.

## Branche

- `v3` — aktywny.
- `legacy` — działający prototyp FastAPI + PostGIS + MapLibre oraz narzędzia Pythonowe do wycinania
  dachów z ortofoto i budowy oznaczonego datasetu (250 cropów w `dataset/pilot`). Zaglądaj tu po wiedzę
  o GUGiK, EPSG:2180 i formacie snapshotów.
- `frontendv2` — porzucone podejście: monorepo pnpm z Express/Prisma/MySQL i Next.js/Leaflet.
- `main` — pusty initial commit.

Nieśledzone pozostałości na dysku po sprzątaniu `v3`: `legacy/`, `packages/`, `node_modules/`
i `.venv/` w katalogu głównym. Można je usunąć — zawartość jest na branchu `legacy`.
