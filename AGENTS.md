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
  - import danych: `.venv/Scripts/python.exe -m scripts.ingest --registry ../Additional_data/geoazbest-mazowieckie.geojson/geoazbest-mazowieckie.geojson --buildings ../Additional_data/budynki-osm-mazowieckie.geojson/budynki-osm-mazowieckie.geojson`
  - samo przeliczenie dopasowan: `.venv/Scripts/python.exe -m scripts.ingest --match`
  - proba bez pelnego importu: dodaj `--limit 50000`
  - serwer dev: `.venv/Scripts/python.exe -m scripts.serve --watch` (bez `--watch` jeden przebieg)
  - testy: `.venv/Scripts/python.exe -m pytest`
  - testy z prawdziwą bazą: ustaw `TEST_DATABASE_URL=postgresql://roofer:roofer@localhost:5433/roofer`
  - lint: `.venv/Scripts/python.exe -m ruff check .` oraz `... -m ruff format --check .`
- Frontend (z katalogu `frontend/`): `pnpm install`, `pnpm dev`, `pnpm test`, `pnpm typecheck`,
  `pnpm lint`, `pnpm build`

Jeden `.env` w katalogu głównym obsługuje oba procesy: backend czyta `../.env`, Vite ma `envDir: '..'`.

## Kontrakt HTTP

Wszystkie trasy backendu siedzą pod `/api` (sonda zdrowia to `/api/health`). Frontend woła
**ścieżki relatywne** na własnym origin, a dev server Vite przekazuje `/api` do FastAPI
(`API_PROXY_TARGET`). Dzięki temu CORS nie zależy od adresu, pod którym otwarto stronę — inaczej
każdy nowy adres (preview, telefon w sieci lokalnej, deploy) wymagałby dopisania origina.
`VITE_API_BASE_URL` ustawiaj tylko wtedy, gdy backend ma stać na innym origin niż frontend.

| Trasa | Co robi |
| --- | --- |
| `GET /api/health` | trzy stany bazy; 503, gdy nie ma bazy albo PostGIS-a |
| `GET /api/tiles/buildings/{z}/{x}/{y}.mvt` | kafle `ST_AsMVT`; od zoomu 14 obrysy, 8–13 centroidy zgłoszonych, niżej 204 |
| `GET /api/buildings/{id}` | dane budynku + dopasowane rekordy rejestru z udziałami |
| `GET /api/buildings/{id}/analysis` | ocena pokrycia dachu; `source` mówi, czy to model, atrapa, czy brak wyniku |
| `GET /api/buildings/{id}/roof.png` | kwadratowy wycinek ortofoto z marginesem (`size` 128–1024) |
| `GET /api/imagery/orthophoto/{z}/{x}/{y}.png` | proxy WMS GUGiK w EPSG:3857, cache w pamięci |
| `POST /api/area/scan` | statystyki prostokąta + do 500 zgłoszonych budynków |
| `GET /api/area/limits` | limit powierzchni zaznaczenia (25 km²) — front nie trzyma własnej kopii |
| `GET /api/geocode?q=` | proxy do Nominatima: 1 zapytanie/s, cache, wymagany `User-Agent` |

## Język wizualny

Tokeny są w bloku `@theme` w `frontend/src/index.css` i **tylko tam**: granat `--color-ink` na tekst,
szarości na drugi plan, jeden akcent `--color-accent`, czerwień `--color-listed` i szarość
`--color-not-listed` na status, `--radius-card` 2 px, `--font-display` (szeryf) na nagłówki i liczby,
klasa `.label-micro` na mikropodpisy kapitalikami.

Zasady, które obowiązują każdy komponent: jasne tło, **włosowe linie 1 px** zamiast cieni (jedyny
dozwolony cień to `shadow-[0_1px_3px_rgba(5,28,44,0.08)]` na panelu nad mapą), promień `rounded-card`
i nigdy więcej, zero `backdrop-blur`, gradientów, półprzezroczystych paneli i kolorowych plakietek.
Status to kwadratowa kropka plus tekst. Zieleń jest **zakazana** dla niezgłoszonych budynków i dla
werdyktu „model nie widzi eternitu" — znaczyłaby „czysty dach", a my wiemy tylko, że nikt nie zgłosił.

Kolory mapy są zdublowane jako hexy w `frontend/src/map/layers.ts`, bo MapLibre nie czyta zmiennych
CSS. Zmieniając jedno, zmień drugie — test `layers.test.ts` pilnuje tylko tego, że nie są zielone.

## Dane w bazie (stan po P1)

| | Wczytane | Wstawione | Odrzucone | Czas |
| --- | ---: | ---: | ---: | ---: |
| rejestr GeoAzbest | 379 122 | 379 011 | 111 (110 zdegenerowanych, 1 poza Polską) | 35 s |
| budynki OSM | 2 585 219 | 2 585 219 | 0 | 302 s |

Oba wyniki „wczytane" zgadzają się z `numberReturned` w stopkach snapshotów. W rejestrze 3 291
geometrii było niepoprawnych i zostało naprawionych przez `ST_MakeValid`; dane Geofabrik są czyste
u źródła. Dopasowanie: 419 321 przecinających się par, 334 310 spełnia regułę, **319 869 budynków
(12,37%) ma dopasowanie**; 128 s. Po każdym imporcie leci `ANALYZE` — bez tego planer po masowym
ładowaniu wybiera złe plany.

Pomiary na pełnych danych: bbox 2×2 km w Śródmieściu to 2 139 budynków w **31,6 ms** z geometrią
jako GeoJSON, a 3 365 budynków z dołączonymi atrybutami rejestru w 47,5 ms. Warunek P1 (100 ms)
spełniony z zapasem.

Baza zajmuje 1 444 MB (`osm_buildings` 1 205 MB, `registry_records` 165 MB,
`building_registry_match` 55 MB). Import sprząta po sobie tabele tymczasowe — bez tego zostaje
w bazie kopia całego snapshotu i rośnie ona do 3,3 GB.

Obszary z mieszanym wynikiem, dobre na demo (komórki 0,01°): lon 21,08 / lat 51,25 — 628 budynków,
341 zgłoszonych (54%); lon 19,97 / lat 53,09 — 48%; lon 21,39 / lat 51,10 — 48%. Warszawa ma 0,1%,
więc na demo nie nadaje się w ogóle.

Sprawdzenie niezależnym źródłem: trzy rekordy z `dataset/pilot/manifest.jsonl`, policzone starym
toolingiem w EPSG:2180, mają w bazie powierzchnie 126,6 / 67,9 / 53,1 m² wobec 126,5 / 67,81 / 53,03
w manifeście. Zgodność do 0,15% potwierdza, że `ST_Area(geography)` zamiast reprojekcji do 2180 jest
wystarczające.

## Fazy

| Faza | Zakres | Gotowe, gdy | Stan |
| --- | --- | --- | --- |
| P0 | Szkielet: PostGIS, FastAPI `/api/health`, mapa MapLibre, testy | mapa renderuje się w przeglądarce, `/api/health` zwraca wersję PostGIS | gotowe 2026-09-20 |
| P1 | Import snapshotów, tabele, dopasowanie budynek↔rejestr | liczby zgadzają się ze stopkami snapshotów, zapytanie o bbox 2×2 km poniżej 100 ms | gotowe 2026-09-20 |
| P2 | Kafle wektorowe `/tiles/buildings/{z}/{x}/{y}.mvt` + kolorowanie | całe województwo przewija się płynnie | gotowe 2026-09-20 |
| P3 | Skan obszaru: rysowanie prostokąta, lista, statystyki | liczby w panelu zgadzają się z mapą | gotowe 2026-09-20 |
| P4 | Karta budynku: atrybuty rejestru, powierzchnia, ortofoto | klik w zgłoszony budynek pokazuje atrybuty i zdjęcie dachu | gotowe 2026-09-20 |
| P5 | Gniazdo na API ML | podmiana jednej zmiennej środowiskowej wpina serwis kolegi | gotowe (atrapa) 2026-09-20 |

Nie zaczynaj fazy, której właściciel nie nazwał.

Poza fazami doszły: trzy podkłady z przełącznikiem (OSM, ortofoto GUGiK, CARTO Positron),
wyszukiwanie miejscowości przez Nominatim, rysowanie prostokąta bez biblioteki, nowy język wizualny.

**Zaległość z listy życzeń właściciela:** heatmapa skupisk rejestru przy oddaleniu mapy. Była wybrana
razem ze skanem obszaru i ortofoto, ale nie powstała — punkty zgłoszonych przy zoomie 8–13 to nie to
samo. Nie usuwaj tego wpisu, dopóki funkcja nie istnieje albo właściciel jej nie odwoła.

## Ocena pokrycia dachu (P5)

Dostawcę wybiera `PREDICTION_PROVIDER`: `mock` (domyślnie) albo `none`; literówka w nazwie daje
`unavailable`, nie wyjątek — zła konfiguracja nie ma prawa pokazać jakiegokolwiek wyniku. Atrapa
liczy się **wyłącznie ze skrótu identyfikatora budynku** i świadomie nie zagląda do
`registry_matches`: udawanie, że niezależna analiza potwierdza zgłoszenie w rejestrze, byłoby
sfabrykowanym dowodem. Osobny test sprawdza, że SQL dostawcy nie dotyka tej kolumny, a `__post_init__`
odrzuca `probability` równe 0 przy werdykcie `unknown`, atrapę z nazwą modelu i model bez nazwy.

W interfejsie atrapa ma nad werdyktem napis „Wynik demonstracyjny · model niepodłączony" i wyszarzoną
liczbę; drugi test pilnuje, że przy `source: "model"` tego ostrzeżenia **nie ma** — inaczej prawdziwy
wynik wyglądałby na podrobiony.

Gdy pojawi się API współpracownika (przyjmuje bbox, oddaje poligony wykrytych dachów): dopisać
`HttpModelProvider` w `app/prediction.py`, przeciąć jego poligony z geometrią budynku
(`ST_Intersects` + największy udział powierzchni, bo serwis oddaje dachy z okolicy) i przestawić
zmienną środowiskową. Trasa, kontrakt i cały frontend zostają bez zmian.

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
11. **`reload=True` uvicorna na tej maszynie nie działa i milczy o tym.** WatchFiles wykrywa zmianę,
    wypisuje „Reloading…", nowy worker nigdy nie wstaje, a **stary dalej odpowiada** — serwer podaje
    stary kod bez żadnego błędu. Dlatego `scripts/serve.py --watch` restartuje cały proces przez
    `watchfiles.run_process`. Sprawdzone podbiciem wersji FastAPI i odczytem `/openapi.json`.
    Nie wracaj do wbudowanego reloadu bez takiego dowodu.
12. **`watchfiles` z `target_type="command"` dzieli komendę `shlex`-em z `posix=False`** na Windowsie,
    więc ścieżki w cudzysłowach docierają z cudzysłowami. Używamy `target_type="function"` ze ścieżką
    modułową `scripts.serve.serve`.
13. **`vitest/config` nie eksportuje `loadEnv`** — `defineConfig` bierz z `vitest/config`,
    a `loadEnv` z `vite`. Inaczej dev server wypisuje „server restart failed" i dalej chodzi
    na starej konfiguracji.
14. **Optymalizator zależności Vite gubi workera MapLibre**
    (`maplibre-gl-worker.mjs ... does not exist`). Naprawia to `optimizeDeps: { exclude: ['maplibre-gl'] }`.
15. **Funkcja PL/pgSQL z blokiem `EXCEPTION` nie może być `PARALLEL SAFE`.** Blok otwiera
    subtransakcję, a w zapytaniu równoległym kończy się to błędem `cannot start subtransactions
    during a parallel operation`. `safe_geojson_geometry` jest `PARALLEL UNSAFE` (migracja 003),
    więc parsowanie geometrii idzie jednowątkowo — i to jest cena za odporność na jeden zepsuty obiekt.
16. **Postgres nie ma `round(double precision, integer)`.** Przy zaokrąglaniu `area_m2` albo
    współrzędnych trzeba rzutować na `numeric`.
17. **`psql -c "VACUUM ...; VACUUM ..."` nie działa** — kilka polecen w jednym `-c` leci w bloku
    transakcji, a `VACUUM` tam nie wchodzi. Każde `VACUUM` w osobnym `-c`.
18. **`ingest` nie commituje sam** — o transakcji decyduje wywołujący. Dzięki temu testy
    integracyjne importują dane na prawdziwym PostGIS-ie i wycofują transakcję, więc nie niszczą
    zaimportowanego województwa.
19. **Tailwind 4 emituje tylko te tokeny z `@theme`, których używa jakaś klasa.** Kolor podany
    w stylu inline przez `var(--color-listed)` nie istnieje w zbudowanym CSS, jeśli żadna klasa
    (`bg-listed`, `text-listed`) go nie dotknęła. Sprawdzone przeszukaniem `dist/assets/*.css`.
20. **Atrapy MapLibre w testach muszą mieć `off`, `removeLayer` i `removeSource`**, i naprawdę
    usuwać, a nie tylko przyjmować wywołanie. Po wpięciu rysowania prostokąta brak `off` wywalił
    szesnaście testów `MapView` naraz, a atrapa, która tylko udaje usuwanie, kłamie w testach
    liczących nasłuchy.
21. **Ponowny import budynków zmienia ich identyfikatory** (`TRUNCATE` nie zeruje sekwencji), więc
    zapisane linki do konkretnego budynku przestają działać. Jeśli kiedyś będą potrzebne trwałe
    adresy, trzeba adresować przez `osm_id`, nie przez klucz z bazy.
22. **`.click()` na elemencie DOM nie przechodzi przez `act()` Reacta** — asercja biegnie przed
    przerysowaniem. W testach używaj `fireEvent.click`.
23. **Elasticsearch: świadomie nie używamy** (decyzja właściciela z 2026-09-20, mimo tracku
    sponsorskiego). Zapytania, które faktycznie wykonujemy, są geometryczne, a atrybutów do
    filtrowania mamy jedno pole — patrz sekcja „Dane". Gdyby wracać do tematu: najpierw bogatsza
    warstwa rejestru, potem podział „PostGIS liczy geometrię, Elastic odpowiada za fasety
    i wyszukiwanie", nigdy odwrotnie i nigdy jako ozdoba.

## Dane

`Additional_data/DATA_MAZOWIECKIE.md` opisuje pochodzenie, licencje i liczebność snapshotów.
Same pliki (0,9 GB budynków OSM, 118 MB rejestru) leżą na dysku nieśledzone przez Gita.

GeoAzbest to **rejestr zgłoszeń** wyrobów azbestowych pozostałych do unieszkodliwienia, bez dat
w warstwie publicznej, i opisuje azbest w obiekcie, nie udowodnione pokrycie dachu. Brak w rejestrze
nie jest dowodem czystego dachu. W UI mów „zgłoszony” / „niezgłoszony” / „nieznany” — nigdy
„wykryto azbest”. Status nieznany zapisujemy jako `null`, nigdy jako `false`.

**Część geometrii w rejestrze to obrysy działek, nie dachów.** Mediana powierzchni rekordu to 99 m²,
p95 to 305 m², ale 1 189 rekordów ma ponad 10 000 m², a największy 73,7 km². Jeden taki poligon
przykrywa w całości każdy budynek w okolicy: przy naiwnej regule „przecięcie pokrywa co najmniej 10%
powierzchni budynku albo rekordu” dawało to 33 899 fałszywych par i obszary w 100% zgłoszone. To nie
są śmieci — takie rekordy mają poprawny `nr_dzialki`, a numer działki jest jedynym atrybutem tej warstwy.

**Rejestr ma dokładnie jeden atrybut.** W snapshocie warstwy `budynki_z_azbestem` jest tylko
`nr_dzialki` — sprawdzone zapytaniem po kluczach JSONB na wszystkich 379 011 rekordach. Z prefiksu
numeru da się wyciągnąć gminę (327 różnych kodów TERYT) i to całe bogactwo. Bogatsza warstwa
`wyroby_dzialki` w WFS GeoAzbest ma według dokumentacji `teryt`, `id_lokalizacji`, ilość wyrobu,
ilość przekazaną do unieszkodliwienia, pilność oraz planowany i faktyczny rok usunięcia — każde
filtrowanie po atrybutach wymaga najpierw jej zaimportowania. Bez tego filtry mogą operować tylko na
statusie, rodzaju budynku, powierzchni i gminie.

**Budynki OSM: `fclass` jest bezużyteczne**, bo warstwa Geofabrik ustawia wszystkim 2 585 219
obiektom wartość `building`. Prawdziwy rodzaj jest we właściwości `type` i trafia do kolumny
`osm_type` (migracja 004): 1 464 391 budynków go ma, najczęściej `detached`, `house`, `outbuilding`,
`farm_auxiliary`. Tłumaczenie na polski jest w `frontend/src/lib/osmBuildingType.ts` i **zawsze**
pokazuje obok surowy tag, bo tłumaczenie jest interpretacją.

Obowiązująca reguła dopasowania (`app/ingest.py`, `MATCH_RULE`): przecięcie musi pokrywać co najmniej
**10% obu** poligonów — co jest równoważne temu, że większy nie jest więcej niż 10× większy od
mniejszego — **albo** co najmniej **50% poligonu rejestru** musi leżeć w budynku (1 754 pary, gdzie
rekord narysowano symbolicznie w środku dużego dachu). Tabela `building_registry_match` trzyma
**każdą** przecinającą się parę z obydwoma udziałami, więc zmiana progu nie wymaga ponownego
liczenia przecięć.

## Konwencje

- Testy piszemy razem z kodem, jednostki małe i sprawdzalne bezpośrednio. To polecenie właściciela.
- Komunikaty dla użytkownika po polsku i konkretne.
- Push do `origin` po każdej fazie i po każdym samodzielnym kroku, bez pytania — ale tylko
  z zielonym drzewem (backend: ruff + pytest, frontend: typecheck + test + lint + build).
- Każde zewnętrzne źródło ma stan „nieznany”; padnięte API nie może wywalić całej odpowiedzi.
- Praca agentami: każdy agent dostaje **rozłączną listę plików**, a kontrakt API, tokeny stylu
  i złożenie ekranu robi agent nadrzędny. Dwóch piszących w jeden plik to gwarantowany konflikt,
  a spójności wizualnej nie da się zlecić trzem niezależnym wykonawcom. Przed commitem stageuj
  **wybiórczo**: `git add backend` w trakcie pracy agenta wciąga jego niedokończone pliki.

## Branche

- `v3` — aktywny.
- `legacy` — działający prototyp FastAPI + PostGIS + MapLibre oraz narzędzia Pythonowe do wycinania
  dachów z ortofoto i budowy oznaczonego datasetu (250 cropów w `dataset/pilot`). Zaglądaj tu po wiedzę
  o GUGiK, EPSG:2180 i formacie snapshotów.
- `frontendv2` — porzucone podejście: monorepo pnpm z Express/Prisma/MySQL i Next.js/Leaflet.
- `main` — pusty initial commit.

Katalog roboczy `v3` jest posprzątany: `legacy/`, `packages/` oraz `node_modules/` i `.venv/`
z katalogu głównego zostały usunięte z dysku 2026-09-20 (zawartość żyje na branchu `legacy`).
Python dla starych narzędzi do ortofoto trzeba będzie postawić od nowa — root `.venv` z rasterio
i shapely już nie istnieje.
