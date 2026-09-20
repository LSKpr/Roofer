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
| `GET /api/tiles/buildings/{z}/{x}/{y}.mvt` | kafle `ST_AsMVT`; od zoomu 14 obrysy (`buildings`), 8–13 siatka gęstości (`listed_density`), niżej 204 |
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

## Heatmapa zagęszczenia zgłoszeń (zoomy 8–13)

Warstwa `listed_density` w kaflu to **siatka**, nie budynki: punkt w środku komórki z jedynym
atrybutem `count`. Obiekty **nie mają identyfikatora**, a warstwa nie jest klikalna — komórka nie
jest budynkiem, więc klik w ciepło nie ma o co zapytać. Klikanie działa dopiero na obrysach od
zoomu 14.

Powód agregacji jest zmierzony, nie estetyczny: surowe centroidy dawały kafel z8 o wadze
**815 371 B generowany 1,1 s** (319 869 zgłoszonych w województwie), a po agregacji **15 882 B
w 0,19 s** — 51× mniej danych, przy 1 009 komórkach zamiast 48 tys. punktów. Cena jest jawna: samo
zapytanie na z8 zwolniło (~110 → ~250 ms), bo grupowanie kosztuje więcej niż wyrzucenie punktów.

Komórka to szerokość kafla / 64, liczona z obwiedni kafla, więc dzieli go bez reszty i ma stale
64 jednostki MVT (~4 px) na każdym zoomie. Siatka jest zaczepiona o **pół komórki**, żeby
`ST_SnapToGrid` dawał środek, a nie róg — inaczej cała gęstość przesuwa się o pół komórki na
północny zachód. Przynależność centroidu do kafla rozstrzyga porównanie współrzędnych w zakresie
**półotwartym** `[min, max)`, a nie operator `&&`: `&&` porównuje obwiednie zapamiętane we `float4`
zaokrąglonym na zewnątrz i wpuszczał jeden budynek zza krawędzi, który sąsiedni kafel liczył drugi
raz. Pilnują tego dwa testy: suma `count` w kaflu równa się liczbie zgłoszonych o centroidzie w tym
kaflu (sprawdzane na sześciu zoomach), a suma czterech kafli z+1 równa się sumie rodzica.

**Do kalibracji na żywej mapie** (dziś szacunki, opisane w `frontend/src/map/layers.ts`): górny próg
wagi `count = 40`, waga minimalna 0,15, promień 12→26 px i intensywność 0,6→1,8 dla zoomów 8→13.
Przy z8 komórka to ~1,5 km i większość zamieszkanych komórek przebija próg, więc kontrast niesie
wtedy liczba niepustych komórek, a nie ich waga.

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

### Model lokalnie (2026-09-20, obecna konfiguracja)

Usługa modelu chodzi **u nas**, nie na cudzym serwerze: `http://127.0.0.1:8020`. To kopia kodu
autora uruchomiona bez zmian — nie przepisywaliśmy modelu ani preprocessingu, bo „prawie takie samo"
centrowanie kadru albo inna normalizacja dałyby liczby wyglądające jak jego wyniki, a nimi nie
będące. `model_id` po obu stronach jest identyczny (`70b702e1…`), i to jest dowód, że liczymy tym
samym modelem.

Powody były dostępnościowe, nie jakościowe: zdalna instancja wymagała tunelu SSH (jej publiczny port
blokuje Security Group), miała zniknąć 20.09.2026 o 18:20 UTC, i raz już przestała działać w środku
pracy — autor przeniósł katalog, a proces uvicorna został ze starą ścieżką i zaczął zwracać 500.

Gdzie co leży (**poza repozytorium**, bo model waży 209 MB, a baza 590 MB):

```text
C:\Users\kacpe\Desktop\HackMIT\ml-service\COPY_FRONT_ALL\
  fastapi_backend\        usluga (FastAPI), .venv obok, token w runtime\api-token
  artifacts\...\model.onnx    209 MB, ONNX na CPU
  Data\build_roof_dataset.py  wspolny preprocessing — usluga go importuje
```

Uruchomienie (Python 3.11 wystarcza, autor testował 3.13):

```bash
cd /c/Users/kacpe/Desktop/HackMIT/ml-service/COPY_FRONT_ALL
./.venv/Scripts/python.exe -m unittest discover -s fastapi_backend/tests   # 16 testow autora
./.venv/Scripts/python.exe -m fastapi_backend.manage create-token          # raz, nie nadpisuje
ROOFER_REQUESTS_PER_MINUTE=120 ./.venv/Scripts/python.exe -m uvicorn \
  fastapi_backend.app:app --host 127.0.0.1 --port 8020 --workers 1 --no-proxy-headers
```

Port 8020, bo 8001 zajmuje nasz backend, a 8010 był tunelem. Token trafia do naszego `.env`
(`PREDICTION_API_TOKEN`), którego nie ma w repozytorium.

**Limity są nasze, nie modelu.** To były zmienne środowiskowe tamtej instancji, więc lokalnie
ustawiamy je sami. Obecnie usługa startuje z `ROOFER_MAX_BUILDINGS=500`, `ROOFER_MAX_AREA_KM2=10`,
`ROOFER_REQUESTS_PER_MINUTE=120`, `ROOFER_TILE_CACHE_BYTES=536870912`, `ROOFER_TILE_CONCURRENCY=16`.
Podniesienie tempa pozwoliło zejść z `PREDICTION_MIN_INTERVAL_S` z 6 s na 0,5 s, więc klikanie
w kolejne budynki nie czeka już na ogranicznik.

**Te liczby muszą być takie same po obu stronach.** Nasza bramka (`MODEL_MAX_BUILDINGS`,
`MODEL_MAX_AREA_KM2` w `app/prediction.py`, nadpisywalne przez `prediction_model_max_*`) istnieje po
to, żeby za duży prostokąt dostał własne 400 z konkretną liczbą w kilkudziesięciu milisekundach,
zamiast czekać kilkanaście sekund na `413` od usługi. Ustawiona niżej blokuje zapytania, które by
przeszły; wyżej — traci cały sens.

**Co naprawdę jest wąskim gardłem: model na CPU, nie pobieranie kafli.** Pomiar rozdzielający,
na tym samym obszarze 464 budynków:

| pomiar | czas |
|---|---:|
| sama inferencja ONNX, 464 kadry, bez sieci | **18,8 s** (40 ms/dach) |
| zapytanie z kaflami w cache | 19,2 s |
| zapytanie z pustym cache kafli | 32,0 s |
| trzy identyczne przebiegi z cache | **41,3 s / 19,2 s / 24,3 s** |

Czyli z kaflami w cache czas odpowiedzi **jest** czasem inferencji, a pobranie kafli dla nowego
obszaru dokłada kilkanaście sekund. Modelu nie da się przyspieszyć: 4 wątki dają 19,9 s, 8 wątków
18,1 s, a 16 wątków **pogarsza** do 23,0 s przez rywalizację o rdzenie; GPU nie ma (Intel Iris Xe).

Najważniejsza liczba w tej tabeli to ostatni wiersz: **dwukrotny rozrzut na identycznej pracy**,
bo laptopowy procesor zjeżdża z taktowaniem. Każdy pojedynczy pomiar czasu na tej maszynie jest
więc niepewny co do czynnika dwa — dlatego panel mówi „up to about", a nie „about"
(`SECONDS_PER_ROOF = 0.18` w `ScanPanel.tsx` to górna granica, nie średnia).

Pułapka, w którą sam wpadłem: pierwsza wersja tych notatek podawała 64,8 s dla tego obszaru
i wnioskowała z tego, że wąskim gardłem są kafle (68% czasu). Ten przebieg **nakładał się na
benchmark 1500 budynków liczący się w tle**, który konkurował o CPU i sieć. Mierząc czas na tej
maszynie, upewnij się, że nic innego nie liczy — inaczej wynik jest o czynnik dwa za duży i prowadzi
do optymalizowania nie tego, co trzeba.

500 budynków (~25-75 s zależnie od stanu procesora) mieści się w 180-sekundowym limicie żądania
z zapasem. Sprawdzone na żywo przez nasz endpoint: 464 budynki, odpowiedź 129 KB, `truncated: false`
(ważne, bo przycięta lista wyłącza suwak progu), 120 niezgłoszonych budynków z flagą. Prostokąt
z 691 budynkami dostaje 400 w **30 ms**.

Cache kafli usługi ma teraz 1 GiB i TTL 12 h (`ROOFER_TILE_CACHE_BYTES`, `ROOFER_TILE_CACHE_TTL`),
więc **obszar pokazywany na demo warto przepuścić przez model raz wcześniej** — drugie przejście po
tych samych kaflach jest szybsze i nie zależy od łącza.

Pomiary z tego samego prostokąta pod Zwoleniem (76 budynków):

| | zdalnie przez tunel | lokalnie |
|---|---:|---:|
| `/v1/analyze` | 2,3 s | **4,8 s** (zimny cache kafli) |
| przez nasz `/api/area/analyze` | 2,3 s | **3,1 s** |
| wynik | 66 ocenionych, 17 z flagą | **identyczny** |

Lokalnie jest wolniej, bo kafle Google idą przez łącze domowe, a nie przez AWS. I to jest druga
rzecz, o której trzeba wiedzieć: model patrzy na **kafle Google Satellite** (zoom 20), a autor sam
pisze, że korzystanie z nich musi być zgodne z warunkami dostawcy. Postawienie usługi u siebie nie
tworzy tego problemu, ale **przenosi go na nas**. Podmiana na ortofoto GUGiK nie jest przełącznikiem:
model trenowano na Google, więc na innym źródle jego skuteczność zmieni się w nieznany sposób.

Przełączenie z powrotem na zdalną instancję (albo na cokolwiek innego) to zmiana `PREDICTION_API_URL`
i tokenu w `.env`. Ani jedna linia naszego kodu nie wie, gdzie stoi model — po to było gniazdo
dostawcy w `app/prediction.py`.

### Lista niezgłoszonych dachów z flagą — właściwy produkt tej aplikacji

Pod liczbami modelu stoi sekcja `Not in the register, flagged by the model (N)`: dachy spełniające
naraz `probability >= próg` i `listed === false`, posortowane malejąco po ocenie, klikalne (otwierają
kartę budynku ze zdjęciem i notą). Liczba prowadząca bez tej listy była bezużyteczna — urzędnik
potrzebuje konkretnych adresów, nie statystyki.

Filtr siedzi w `lib/modelStats.ts` (`selectFlaggedNotListed`) obok `recountStats`, bo to ten sam
warunek progu; w komponencie żyłby w dwóch miejscach i pierwsza poprawka rozjechałaby listę z liczbą
nad nią. Osobny test wiąże długość listy z `suspectedNotListed` dla pięciu progów.

**Ta sekcja najłatwiej w całej aplikacji zamienia się w donos**, więc wymuszone jest w niej trzy razy
to samo, innymi słowami: że model porównuje wygląd pokrycia na zdjęciu satelitarnym (77% trafności,
63% wykrywalności), że brak w rejestrze znaczy tylko „nikt nie zgłosił" — nie „nielegalne" i nie
„właściciel zataił" — i wprost, że to jest **lista do sprawdzenia w terenie, nie lista ustaleń**.
Zdania nie znikają, gdy lista jest pusta, bo dotyczą sekcji, nie wierszy.

### Strumieniowanie: `POST /api/area/plan` i analiza kawałkami

Model przyjmuje 500 budynków na żądanie, a skan sięga 25 km², więc obszar dzielimy na kawałki
i analizujemy je po kolei, publikując wynik po każdym. Dzięki temu limit 500 przestał być granicą
tego, co użytkownik może zaznaczyć, a pomarańczowe obrysy i liczby pojawiają się w trakcie.

`/api/area/plan` dzieli prostokąt **połową po dłuższym boku mierzonym w metrach** (nie ćwiartkami:
te mnożą liczbę zapytań do modelu ×4, a każde to kilkadziesiąt sekund inferencji; nie w stopniach,
bo na 51. paraleli stopień długości ma 70 km wobec 111 km stopnia szerokości i kawałki wychodziłyby
coraz węższe). Koszt to `2N − 1` zapytań do bazy, twardo ≤ 127. Puste kawałki odpadają bez dalszego
podziału. Zmierzone: 691 budynków → 2 kawałki w 50 ms; 3 310 w Warszawie → 12 kawałków w 330 ms;
24 km² w Śródmieściu → 31 kawałków pokrywających 98,4% i `truncated: true`, bo jeden blok 0,38 km²
ma ponad 500 budynków.

Trzy rzeczy, bez których strumieniowanie kłamie:

- **Deduplikacja po `osm_id` jest obowiązkowa.** Budynek na linii cięcia wraca w dwóch kawałkach
  (12 z 703 w prostokącie testowym, 176 z 3 486 w Warszawie). Bez niej byłby liczony dwa razy
  w każdej statystyce i dwa razy na liście.
- **`noResult` jest przybliżeniem** i jest to jedyne takie miejsce: backend nie oddaje
  identyfikatorów dachów bez oceny, więc taki dach stojący dokładnie na cięciu policzy się dwa razy.
  Opisane komentarzem w `mergeAnalyses`.
- **Wynik częściowy musi się przedstawiać**: dopóki nie spłynęły wszystkie kawałki, przy liczbach
  stoi `These numbers cover 3 of 7 areas analysed so far.` Bez tego zdania częściowe „120 flagged"
  czyta się jak wynik końcowy.

Zamknięcie panelu albo nowe zaznaczenie **przerywa pętlę**, a nie tylko chowa wynik — inaczej
w tle zostają minuty zapytań do modelu. Błąd jednego kawałka zostawia to, co już spłynęło, i pokazuje
komunikat; wyrzucanie kilku minut inferencji z powodu jednego 503 byłoby najgorszym zachowaniem.

Jedyny limit, który został na wejściu, to budżet czasu: **`MAX_STREAM_ROOFS = 2000`** w `ScanPanel`
(przy 40–115 ms na dach to 1,5–4 minuty; 10 631 budynków w centrum Warszawy to kwadranse).

Sprawdzone na żywo: 822 budynki, 2 kawałki, 37,8 s razem — po pierwszym kawałku 105 niezgłoszonych
z flagą, po drugim 211.

### Analiza całego zaznaczonego obszaru

`POST /api/area/analyze` przepuszcza prostokąt przez model jednym żądaniem i zestawia jego ocenę
z naszym rejestrem. Liczba prowadząca to **`suspectedNotListed`**: budynki, których nikt nie
zgłosił, a model widzi na nich pokrycie typu eternit. Na żywo pod Zwoleniem (76 budynków, 2,3 s):
66 ocenionych, 10 bez oceny, 17 z flagą, **14 niezgłoszonych z flagą**.

Trzy zasady liczenia, każda pilnowana testem:

- **mianownikiem udziału jest `analysed`, nigdy `analysed + noResult`** — dach bez oceny jest
  nieznany, a nie czysty, i doliczenie go zaniżałoby wynik akurat tam, gdzie zdjęcie było najgorsze;
- **budynek zgłoszony, którego model nie ocenił, nie liczy się jako „model nic nie widzi"**;
- **budynek, którego nie ma w naszej bazie, nie wchodzi do żadnego licznika** i jest widoczny jako
  `unknownToUs`. Wcześniej dostawał `listed=false` i lądował w liczbie prowadzącej — a „nie ma go
  u nas" nie znaczy „nikt go nie zgłosił". Przy wspólnym snapshocie OSM to zawsze zero; niezerowe
  znaczy, że snapshoty się rozjechały, i właśnie dlatego jest widoczne, a nie połknięte.

Limity modelu (100 budynków, 4 km²) sprawdzamy **po naszej stronie, zanim cokolwiek wyślemy**:
liczbę budynków znamy z własnej bazy, więc 400 z konkretną liczbą przychodzi w 8–44 ms zamiast po
kilku sekundach czekania na cudze 413. Limity wystawia `GET /api/area/limits` w polu `model`, żeby
front ich nie zgadywał.

Na mapie: **pomarańczowy obrys** (`--color-suspected`, `#ed8b00`) nad warstwami budynków, pod
podświetleniem wyboru. Obrys, nie wypełnienie — czerwone wypełnienie znaczy „jest w rejestrze"
(fakt), pomarańczowy obrys „model coś widzi" (domysł ze zdjęcia). Dzięki temu widać jedno i drugie
naraz, a przypadek szarego wypełnienia z pomarańczowym obrysem to dokładnie ten, po który sięga
urzędnik. Warstwa nie jest klikalna: klik ma trafiać w budynek i otwierać jego kartę.

### Prawdziwy model jest podłączony (2026-09-20)

`PREDICTION_PROVIDER=model` woła `POST {PREDICTION_API_URL}/v1/analyze` z tokenem Bearer. Sprawdzone
na żywo: nasz `/api/buildings/27469148/analysis` oddaje `source: "model"`, `probability: 0.2414`
i `modelName` równe `meta.model_id` tamtego serwisu.

**Dopasowanie idzie po `source_id`, nie geometrycznie.** Serwis korzysta z tego samego snapshotu OSM
(jego `/health` podaje 2 585 219 budynków, czyli nasza liczba co do jednego) i sam oddaje `source_id`
równy naszemu `osm_id`. Przecinanie poligonów byłoby tu gorsze i niepotrzebne: w prostokącie jednego
budynku siedzą sąsiednie dachy — przy pierwszym żywym zapytaniu obok bloku wyszedł garaż sąsiada.

**Sieć.** Publiczny port 8000 tamtej instancji jest odfiltrowany przez Security Group (port 22
odpowiada w 21 ms, porty 80/443/8000 dają timeout), więc jedyna droga to tunel SSH. Lokalnie **8010**,
bo na 8001 stoi nasz backend:
`ssh -N -L 8010:127.0.0.1:8000 student@<host>`

**Limity tamtej instancji:** 10 zapytań na minutę, jedno naraz, 100 budynków i 4 km² na żądanie
(sprawdzone: większy prostokąt dostaje `413 TOO_MANY_BUILDINGS`). Karta pyta o ocenę przy każdym
kliknięciu, więc `HttpModelProvider` ma cache po `osm_id` (drugie pytanie: 8 ms zamiast 7,8 s)
i odstęp między żądaniami. 429 nie jest ponawiane w pętli — oddajemy „nie wiemy" z czasem z
`Retry-After`.

**Model patrzy na inne zdjęcie niż użytkownik**: Google Satellite zoom 20, a karta pokazuje
ortofotomapę GUGiK. Każda nota mówi to wprost, razem ze skutecznością podaną przez autora
(77% trafności, 63% wykrywalności azbestu). Bez tego zdania ktoś porówna ocenę z kadrem obok
i wyciągnie wniosek z dwóch różnych źródeł.

Statusy tamtego API wchodzą w nasze trzy stany bez naciągania: `ok` → `suspected`/`unlikely` po progu
0,5, a `low_quality`, `imagery_error` i `geometry_error` → `unknown` z `probability: null` i powodem
z pola `reasons`. Autor sam rozróżnia „sprawdziłem i nie widzę" od „nie sprawdziłem", więc nie
musieliśmy tego zgadywać.

Pierwszy pomiar zgodności z rejestrem (74 budynki pod Zwoleniem, 64 z oceną): zgłoszone w GeoAzbest
mają średnią ocenę **0,512**, niezgłoszone **0,282**. Próba jest mała (3 zgłoszone), więc to sygnał,
nie dowód — ale kierunek się zgadza, a 14 niezgłoszonych budynków dostało ocenę powyżej 0,5.

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
21. **Budynki adresujemy przez `osm_id`, nie przez klucz z sekwencji.** Ponowny import przesuwa
    klucze (`TRUNCATE` nie zeruje sekwencji: było poniżej 2 585 220, po drugim imporcie
    2 585 326–5 170 544), więc zapisane adresy przestawały działać. `osm_id` jest wypełniony,
    unikalny, całkowity i dodatni dla wszystkich 2 585 219 budynków — od migracji 006 pilnuje tego
    **unikalny** indeks, żeby duplikat w przyszłym snapshocie przerwał import głośno. `id` zostaje
    wewnętrznym kluczem złączeń (`building_registry_match.building_id`); na zewnątrz — w kaflach,
    w `/api/buildings/{osm_id}` i na liście ze skanu — widać wyłącznie `osm_id`. Pole `osmId`
    zniknęło z odpowiedzi, bo było tą samą liczbą w drugim typie.
22. **Kafle nie mogą mieć `max-age`.** To był prawdziwy błąd, nie teoria: po ponownym imporcie
    przeglądarka przez godzinę podawała kafle ze starymi identyfikatorami obiektów, klik wysyłał
    nieistniejący numer i karta budynku pokazywała 404. Teraz kafle idą z `Cache-Control: no-cache`
    i słabym `ETag` zbudowanym z tokenu z tabeli `data_version` oraz współrzędnych; `If-None-Match`
    daje 304 **bez odpytywania PostGIS-a** (2,2 ms i zero bajtów wobec 39 ms i 45 KB na gęstym
    kaflu). `ingest()` i `match()` podbijają token w tej samej transakcji co dane, więc nie ma stanu
    „nowe dane, stary token". Konsekwencja: **import wymaga migracji 005** i bez niej przerwie się
    głośno — świadomie, bo cichy brak tokenu to powrót tego samego błędu.
    ETag nosi dodatkowo `TILE_SCHEMA_VERSION` z `app/dataversion.py`, bo zmiana **znaczenia** kafla
    jest zmianą kodu, której token danych nie unieważni: przejście na `osm_id` bez tego składnika
    odtworzyłoby ten sam błąd 404. **Każda zmiana treści albo znaczenia kafla wymaga podbicia tej
    stałej.**
23. **`ST_AsMVT` nie daje powtarzalnych bajtów** — ten sam kafel przy niezmienionych danych oddał
    45 034 B i 44 979 B, bo zapytanie nie ma `ORDER BY`, a kolejność obiektów zależy od planu.
    Dlatego ETag jest słaby (`W/`): obiecuje tę samą treść, nie te same bajty.
24. **Ortofoto zostaje z `max-age=86400`** — zdjęcie z konkretnego nalotu jest niezmienne, więc
    problem z punktu 22 tam nie istnieje.
25. **`.click()` na elemencie DOM nie przechodzi przez `act()` Reacta** — asercja biegnie przed
    przerysowaniem. W testach używaj `fireEvent.click`.
26. **`ST_AsMVT` ustawia identyfikator obiektu tylko dla kolumny całkowitej — i milczy, gdy jej nie
    ma.** Kolumna `text` (jak surowy `osm_id`) zostanie po cichu doklejona jako zwykły atrybut,
    a kafel wyjdzie bez identyfikatorów i klikanie przestanie działać bez żadnego błędu. Dlatego
    w zapytaniu jest `b.osm_id::bigint AS id`, a nazwa kolumny i piąty argument `ST_AsMVT` pochodzą
    z jednej stałej.
27. **Rzutuj parametr, nie kolumnę.** `WHERE osm_id::bigint = 27469148` daje `Parallel Seq Scan`
    i **263,8 ms**, a `WHERE osm_id = %(id)s::text` idzie po indeksie w **0,4 ms**. Zmierzone
    `EXPLAIN (ANALYZE)` na pełnych danych; test integracyjny pilnuje, że w planie nie ma `Seq Scan`.
28. **Sekret w `Settings` musi być `SecretStr`.** Pydantic wypisuje cały obiekt ustawień w
    komunikacie błędu, więc token trzymany jako `str` wyciekł do pierwszego lepszego tracebacku —
    zobaczyłem go w wydruku testu, który sprawdzał coś zupełnie innego. `SecretStr` maskuje
    wartość w `repr`, `str` i `model_dump`; kod sięga po nią jawnie przez `get_secret_value()`.
29. **Diakrytyki: komentarze bez, komunikaty z.** Zasada „bez znaków diakrytycznych" dotyczy
    komentarzy i identyfikatorów w kodzie. Noty i błędy czyta użytkownik w interfejsie i „Ocena
    z jednego zdjecia satelitarnego" wygląda tam na usterkę, a nie na decyzję.
30. **Elasticsearch: świadomie nie używamy** (decyzja właściciela z 2026-09-20, mimo tracku
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
