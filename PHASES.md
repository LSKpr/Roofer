# PHASES.md — prompty startowe

Do każdej fazy jeden prompt. Wklejasz go w nowej sesji **razem z `PROJECT.md`** (albo po nim,
jeśli agent ma już plik w kontekście). Kolejność jest wiążąca — patrz tabela zależności w §10 PROJECT.md.

Na koniec każdej sesji użyj promptu domykającego z dołu tego pliku.

---

## F0 — Fundament

```
Faza F0 z PROJECT.md. Zakres: tylko fundament, żadnej logiki domenowej.

Zrób:
- monorepo pnpm workspaces z paczkami: database, validation, backend, frontend
  (asbestos-checker dodamy w F7)
- root package.json ze skryptami: dev:backend, dev:frontend, db:generate, db:migrate,
  build, docker:up, docker:down
- docker-compose.yml z samym MySQL 8 (healthcheck, wolumen na dane)
- wspólny tsconfig bazowy + per-paczka, eslint, .gitignore
- .env.example w rootcie i w każdej paczce, która czegoś potrzebuje
- STATUS.md z tabelą faz F0–F10 (kolumny: faza, status, data, notatka) i pustą sekcją
  "Długi techniczne"; oznacz F0 jako w trakcie

Nie twórz: schematu Prisma, endpointów, komponentów Reacta.

Gotowe, gdy: pnpm install przechodzi, docker compose up -d stawia MySQL i healthcheck jest zielony,
pnpm build nie zgłasza błędów. Na koniec zaktualizuj STATUS.md.
```

---

## F1 — Kontrakt i model danych

```
Faza F1 z PROJECT.md. To jest faza kontraktu — po niej zmiana schematu wymaga mojej zgody.

Zrób:
- packages/database: schema.prisma z modelem Building dokładnie jak w §5 PROJECT.md
  (trzy stany azbestu, indeksy na centroid i statusy), klient eksportowany z src/index.ts,
  pierwsza migracja
- spec/openapi.yaml: cztery endpointy z §6 PROJECT.md, pełne schematy Building, BBoxStats,
  koperta { data, error }, kody błędów 400/404/500
- packages/validation: schematy Zod dla requestów i odpowiedzi; limit bbox jako JEDNA
  eksportowana stała (MAX_BBOX_AREA_DEG2 = 0.0005) używana potem i w backendzie, i we froncie
- konfiguracja @hey-api/openapi-ts w paczce frontend + skrypt generate:client

Uwaga na strategię typów: Prisma = źródło prawdy dla encji, Zod tylko dla HTTP.
Nie duplikuj pól Building w Zod jako osobnego modelu domenowego.

Gotowe, gdy: prisma migrate dev tworzy tabelę w MySQL, prisma generate przechodzi,
generate:client produkuje types.gen.ts bez błędów. Zaktualizuj STATUS.md.
```

---

## F2 — Szkielet backendu

```
Faza F2 z PROJECT.md. Sam szkielet HTTP — bez integracji zewnętrznych, bez logiki azbestowej.

Zrób w packages/backend:
- app.ts: express, cors, express.json, GET /health, router pod /api, errorHandler na końcu
- middleware/validate.ts: fabryka biorąca schemat Zod i źródło ('body'|'query'|'params'),
  zwracająca 400 z { message, code: 'VALIDATION_ERROR', details }
- middleware/asyncHandler.ts, middleware/errorHandler.ts (klasa AppError + mapowanie błędów
  Prisma P2002 → 409, P2025 → 404), middleware/response.ts (sendSuccess/sendError)
- routes/index.ts z czterema trasami z §6; kontrolery na razie zwracają zaślepki
- index.ts z dotenv i startem serwera na PORT z env

Gotowe, gdy: GET /health odpowiada 200, POST /api/bbox z błędnym body daje 400 z listą
błędów Zod, a bbox większy niż limit też jest odrzucany. Zaktualizuj STATUS.md.
```

---

## F3 — Mock danych i mapa

```
Faza F3 z PROJECT.md. Cel: zobaczyć mapę z danymi, zanim istnieją prawdziwe integracje.

Backend:
- POST /api/bbox generuje 30-80 nienachodzących na siebie prostokątnych budynków wewnątrz
  przesłanego bbox, z losowymi statusami (~15% isAsbestos, ~25% isPotentiallyAsbestos true,
  kilka null, reszta false) i policzonymi stats. Sztuczne opóźnienie 1,5 s.
  Wydziel to do services/mockBuildingService.ts — w F6 podmienimy je na Overpass, reszta zostaje.

Frontend:
- layout.tsx jako komponent kliencki: QueryClient przez useState(() => new QueryClient(...))
  ze staleTime 60s, refetchOnWindowFocus false, retry 1; Toaster; font z subsetem latin-ext
- globals.css: klasa .panel (białe tło, radius 12px, padding, miękki cień)
- components/Loader.tsx: pełnoekranowa nakładka ze spinnerem i propem message
- app/page.tsx: mapa przez dynamic(..., { ssr: false }) — Leaflet nie przeżyje SSR
- features/map/components/Map.tsx: MapContainer na całe okno, zoomControl={false} +
  <ZoomControl position="topleft" />, dwie warstwy w LayersControl (standardowa i satelitarna,
  klucz do satelity z env), zawsze z attribution

Konwencja z-index od tej pory: panele z-[1000], elementy przy kontrolkach Leafleta z-[500].

Gotowe, gdy: mapa renderuje się w przeglądarce bez błędów SSR, a curl na /api/bbox zwraca
sensowne budynki. Zaktualizuj STATUS.md.
```

---

## F4 — Zaznaczanie obszaru i dane

```
Faza F4 z PROJECT.md. Połączenie mapy z API.

Zrób:
- features/map/components/RectangleDrawer.tsx: leaflet-draw z włączonym wyłącznie rectangle,
  narysowane warstwy w L.FeatureGroup w refie, na L.Draw.Event.CREATED policz bbox z getBounds()
  i wywołaj onBBoxDrawn. Walidacja wielkości przez stałą MAX_BBOX_AREA_DEG2 z packages/validation
  — za duży obszar daje toast.error, nie alert(). Prop isLoading blokuje narzędzie.
  Dwa przyciski: "Wyczyść zaznaczenie" i "Wyczyść wyniki". W cleanupie useEffect odepnij handler
  i kontrolkę, inaczej w trybie dev zamontują się dwie.
- features/map/hooks/useBuildings.ts: useBBoxBuildings() jako useMutation na wygenerowanym SDK;
  odpowiedź ma kształt { data, error } — rzucaj Error z response.error.message
- w Map.tsx: stan buildings/stats/currentBBox; kolejne skany KUMULUJĄ się, nie nadpisują;
  deduplikacja po id; nigdy nie mutuj tablicy ze stanu (żadnego splice); toasty na sukces i błąd;
  Loader w trakcie mutation.isPending

Gotowe, gdy: rysuję prostokąt i widzę dane z mocka w stanie, drugi obszar dokłada się do
pierwszego bez duplikatów, za duży obszar nie wysyła żądania. Zaktualizuj STATUS.md.
```

---

## F5 — Wizualizacja

```
Faza F5 z PROJECT.md. Po tej fazie aplikacja ma wyglądać jak produkt.

Zrób:
- render <Polygon> per budynek. API zwraca [lng, lat], Leaflet chce [lat, lng] — zrób jedną
  funkcję konwertującą i używaj tylko jej
- stała COLORS (asbestos #EF4444, potentiallyAsbestos #F59E0B, clean #10B981, unknown #6B7280)
  w jednym miejscu; funkcja getBuildingColor(building); ta sama stała zasila legendę i później wykres
- pathOptions: fillOpacity 0.5, weight 2
- Popup: status po polsku, adres i miasto jeśli są, w przeciwnym razie centroid z 5 miejscami,
  data aktualizacji
- legenda w prawym dolnym rogu (klasa .panel), widoczna gdy są budynki
- panel "Jak używać" w prawym górnym rogu, widoczny dopóki nie ma żadnych wyników:
  wyszukaj lokalizację → wybierz narzędzie prostokąta → narysuj obszar → poczekaj

Gotowe, gdy: mapa jest kolorowa, kliknięcie budynku pokazuje popup, legenda się zgadza
z kolorami wielokątów. Zaktualizuj STATUS.md.
```

---

## F6 — Overpass API i cache

```
Faza F6 z PROJECT.md. Podmiana mocka na prawdziwe budynki z OpenStreetMap.

Zrób w backendzie:
- services/overpassService.ts: zapytanie Overpass QL z §7.1 (way + relation z tagiem building,
  out geom), timeout 30 s, konwersja geometrii na polygon [[lng, lat], ...], obliczanie centroidu
- przepisanie kontrolera /bbox: dla każdego budynku sprawdź w MySQL po centroidzie z tolerancją
  ±0.0001°; istniejące zwróć z bazy, nowe zapisz; policz stats z wyniku końcowego
- obsługa błędów Overpass (429, 504, timeout) — czytelny komunikat, nie surowy stack
- mockBuildingService zostaje w repo, włączany zmienną środowiskową USE_MOCK_DATA=true,
  żeby demo działało nawet przy padniętym Overpassie

Na razie isAsbestos zostaw false, isPotentiallyAsbestos null — to przychodzi w F7 i F8.

Gotowe, gdy: widzę prawdziwe kształty budynków z OSM, a drugi skan tego samego obszaru wraca
z bazy poniżej 100 ms (zmierz i zaloguj czas). Zaktualizuj STATUS.md.
```

---

## F7 — Baza Azbestowa (WMS)

```
Faza F7 z PROJECT.md. Potwierdzanie azbestu z oficjalnego źródła — mechanizm opisany w §7.2.

Zrób nową paczkę packages/asbestos-checker (zależność: sharp):
- checkBuildingForAsbestos(polygon): bbox budynku + 20% marginesu, wymuszenie kwadratu,
  pobranie kafelka WMS 256×256 (LAYERS=budynki_z_azbestem, SERVICE=WMS, VERSION=1.1.1,
  REQUEST=GetMap, SRS=EPSG:4326, FORMAT=image/png, TRANSPARENT=TRUE)
- analiza pikseli: pomiń przezroczyste, dopasuj kolor #2c8900 z tolerancją 10 (odległość
  euklidesowa RGB), przelicz pozycję piksela na lat/lng (oś Y odwrócona!), sprawdź
  ray-castingiem czy punkt leży wewnątrz wielokąta budynku
- co najmniej jeden trafiony piksel → true
- batchCheckBuildings(buildings, concurrency = 20) zachowujące kolejność wyników
- walidacja wejścia: minimum 3 punkty, każdy jako para liczb

W backendzie: services/asbestosCheckService.ts opakowujący bibliotekę — błąd pojedynczego
budynku loguj i zwróć false, nie przerywaj całego skanu. Podłącz w /bbox.

Gotowe, gdy: na obszarze, o którym wiem, że są tam zgłoszone budynki, część wielokątów
robi się czerwona. Zmierz, ile trwa sprawdzenie 50 budynków. Zaktualizuj STATUS.md.
```

---

## F8 — Serwis ML

```
Faza F8 z PROJECT.md. Predykcja dla budynków bez potwierdzenia w bazie.

Zrób serwis w api/ (FastAPI):
- pobieranie kafelków satelitarnych wycentrowanych na centroidzie (zoom 20, wycinek 128 px),
  asynchronicznie, na jednej współdzielonej sesji aiohttp z poolingiem połączeń
- preprocessing zgodny z treningiem: ta sama normalizacja (mean/std zapisane razem z modelem,
  nie przepisane ręcznie), kolejność kanałów CHW
- inferencja przez onnxruntime, model z artifacts/asbestos_net.onnx, ładowany raz na starcie
- POST /predict (pojedynczy) i POST /batch_predict: wejście { coordinates: [{ centroidLat,
  centroidLng, id? }] }, wyjście { results: [{ id, centroidLat, centroidLng,
  isPotentiallyAsbestos: float, success, error? }], total, successful, failed }
- semafor na równoległość pobierania i batchowanie inferencji; błąd pojedynczej współrzędnej
  zwraca success: false, nie wywala całego żądania
- GET /health

W backendzie: services/mlService.ts — próg 0.7 na boolean, timeout 30 s, a przy każdym błędzie
zwróć null dla wszystkich budynków (nie false!). Uruchamiaj razem z asbestos-check przez
Promise.all, nie sekwencyjnie.

Jeśli nie ma jeszcze wytrenowanego modelu: postaw serwis z zaślepką zwracającą stałe 0.0
i oznacz to w STATUS.md jako dług techniczny.

Gotowe, gdy: budynki bez potwierdzenia dostają pomarańczowy kolor, a wyłączenie serwisu ML
nie psuje skanu — wszystko robi się szare. Zaktualizuj STATUS.md.
```

---

## F9 — Statystyki i raport

```
Faza F9 z PROJECT.md. Warstwa raportowa.

Zrób:
- StatsPieChart.tsx (Recharts): ResponsiveContainer w kontenerze o stałej wysokości,
  etykiety procentowe, tooltip z liczbą budynków, kategorie z zerem odfiltrowane,
  kolory z tej samej stałej COLORS co mapa
- panel statystyk w prawym górnym rogu (zastępuje panel "Jak używać" gdy są wyniki):
  wykres + cztery wiersze liczbowe. Liczby licz z tablicy budynków w useMemo, nie trzymaj
  ich w osobnym stanie — inaczej panel, mapa i PDF pokażą różne wartości.
  Sprawdź, czy etykiety zgadzają się z polami: "Czyste" to budynki sprawdzone bez azbestu,
  a nie unknown.
- lib/exportPDF.ts (jsPDF + jspdf-autotable): tytuł, data, współrzędne obszaru, podsumowanie
  z udziałami procentowymi, tabela budynków (adres lub współrzędne, miasto, status) z wierszami
  azbestowymi wyróżnionymi tłem, numeracja stron
- polskie znaki: osadź font TTF dołączony do repo przez addFileToVFS + addFont, z fallbackiem
  na helvetica. Nie pobieraj fontu z CDN w czasie działania.
- przycisk eksportu na dole panelu ze stanem ładowania i toastem

Gotowe, gdy: PDF się pobiera, ma poprawne "ł", "ę", "ż" i liczby zgodne z panelem.
Zaktualizuj STATUS.md.
```

---

## F10 — Dopracowanie i deploy

```
Faza F10 z PROJECT.md. Ostatnia faza: dopracowanie i uruchomienie całości.

UX i wydajność:
- filtry kategorii (pokaż/ukryj czerwone, pomarańczowe, zielone) — filtrowanie po stronie klienta
- Escape anuluje rysowanie; responsywność poniżej 768 px (panele zwijane w dolny arkusz)
- dostępność: aria-label na przyciskach ikonowych, widoczny focus, obsługa klawiatury w wyszukiwarce
- lista wielokątów w osobnym komponencie z memo; rozważ preferCanvas na MapContainer przy
  kilku tysiącach budynków

Deploy:
- Dockerfile dla backendu, frontendu (next.config z output: 'standalone') i serwisu ML
- docker-compose-prod.yml: cztery usługi we wspólnej sieci, healthcheck na backendzie,
  frontend startuje dopiero gdy backend jest zdrowy
- NEXT_PUBLIC_API_URL musi być przekazany jako build arg — zmienne NEXT_PUBLIC są wstrzykiwane
  przy next build, nie w runtime. To najczęstszy powód "działa lokalnie, nie działa po deployu".
- README: wymagania, zmienne środowiskowe, uruchomienie dev i prod, tryb mock

Sprzątanie: usuń console.log, nieużywane importy i martwy kod z poprzednich faz.

Gotowe, gdy: docker compose -f docker-compose-prod.yml up na czystej maszynie stawia całość
i pełny scenariusz demo przechodzi od początku do końca. Zaktualizuj STATUS.md.
```

---

## Prompt domykający fazę

Użyj go na końcu każdej sesji, zanim przejdziesz dalej:

```
Zamykamy fazę. Zrób trzy rzeczy:

1. Sprawdź warunek "Gotowe, gdy" dla tej fazy — uruchom to, co trzeba uruchomić, i pokaż wynik.
   Jeśli coś nie przechodzi, powiedz wprost i nie oznaczaj fazy jako skończonej.
2. Zaktualizuj STATUS.md: status fazy, data, jedno zdanie co działa, oraz wszystko, co zostało
   odłożone, w sekcji "Długi techniczne".
3. Wypisz krótko: co warto sprawdzić ręcznie przed kolejną fazą i czy coś z tej fazy zmienia
   założenia z PROJECT.md.

Nie zaczynaj kolejnej fazy.
```

## Prompt naprawczy (gdy coś z poprzedniej fazy nie działa)

```
Nie zaczynamy nowej fazy. Wracamy do fazy <numer> z PROJECT.md, bo <opis objawu>.

Najpierw zdiagnozuj: pokaż mi, gdzie leży przyczyna, zanim cokolwiek zmienisz.
Napraw minimalnie — bez refaktoryzacji przy okazji i bez zmian w kontrakcie API,
chyba że to właśnie kontrakt jest źródłem problemu (wtedy zapytaj).
Na koniec dopisz przyczynę do sekcji "Długi techniczne" w STATUS.md, jeśli zostawiasz obejście.
```
