# PROJECT.md — System detekcji dachów azbestowych

> Wklej ten plik na start sesji z agentem kodowym. Opisuje CO budujemy, JAK to ma być zbudowane
> i W JAKIEJ KOLEJNOŚCI. Agent ma się go trzymać i nie zmieniać stacku bez pytania.

---

## 0. Jak pracujemy — protokół faz

**Implementuję ten projekt fazami. Agent pracuje wyłącznie nad fazą, którą nazwę w danej sesji.**

Zasady, których trzymamy się przez cały projekt:

1. **Jedna faza = jedna sesja.** Nie zaczynaj kolejnej fazy, nawet jeśli „i tak by się przydała”.
   Nie dopisuj kodu z przyszłych faz „na zapas”.
2. **Zaczynasz od przeczytania stanu.** Na starcie fazy sprawdź, co już istnieje w repo, i powiedz
   jednym akapitem: co zastałeś, co zamierzasz zrobić, czego brakuje. Dopiero potem pisz kod.
3. **Kończysz działającym stanem.** Faza jest skończona, gdy spełniony jest jej warunek
   „Gotowe, gdy” z sekcji 10 — sprawdzony uruchomieniem, nie deklaracją.
4. **Aktualizujesz `STATUS.md`** (tworzysz go w F0): tabela faz ze statusem, data, jednozdaniowa
   notatka co działa, oraz sekcja „Długi techniczne” z rzeczami świadomie odłożonymi.
5. **Blokada zamiast obejścia.** Jeśli coś z tej fazy jest niewykonalne (padłe zewnętrzne API,
   brak klucza, brak modelu) — zatrzymaj się, napisz co blokuje i zaproponuj rozwiązanie
   tymczasowe. Nie udawaj, że działa.
6. **Nie refaktoryzuj poprzednich faz bez powodu.** Jeśli coś naprawdę trzeba zmienić, powiedz
   co i dlaczego, zanim to ruszysz.
7. **Zmiana kontraktu = osobna decyzja.** Każda zmiana w `spec/openapi.yaml` lub schemacie Prisma
   po fazie F1 wymaga mojej zgody i regeneracji klienta.

Prompty startowe do poszczególnych faz są w pliku `PHASES.md`.

---

## 1. Problem i cel

Gminy w Polsce mają obowiązek inwentaryzacji wyrobów azbestowych. Dziś robi się to ręcznie:
urzędnik ogląda ortofotomapę albo jeździ w teren. Oficjalna Baza Azbestowa (`bazaazbestowa.gov.pl`)
jest niekompletna — zawiera tylko to, co właściciele sami zgłosili.

**Budujemy aplikację webową, w której urzędnik zaznacza obszar na mapie i dostaje listę budynków
z oznaczonym statusem azbestu** — z dwóch niezależnych źródeł:

1. **Potwierdzenie** — budynek figuruje w oficjalnej Bazie Azbestowej (pewne).
2. **Predykcja ML** — model rozpoznaje dach azbestowy ze zdjęcia satelitarnego (podejrzenie).

Wynik: kolorowa mapa + statystyki + raport PDF do dokumentacji urzędowej.

**Użytkownik docelowy:** pracownik wydziału ochrony środowiska w urzędzie gminy. Nie jest
technikiem. Musi móc: znaleźć adres, zaznaczyć obszar, zobaczyć wynik, wyeksportować raport.

---

## 2. Architektura

```
┌──────────────────┐   REST/JSON    ┌──────────────────┐
│    FRONTEND      │ ◄────────────► │     BACKEND      │
│  Next.js + React │                │ Express + Prisma │
│  Leaflet (mapa)  │                │                  │
└──────────────────┘                └────────┬─────────┘
                                             │
              ┌──────────────┬───────────────┼───────────────┐
              ▼              ▼               ▼               ▼
        ┌──────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
        │  MySQL   │  │  Overpass  │  │ WMS Bazy   │  │ ML Service │
        │  (cache) │  │  API (OSM) │  │ Azbestowej │  │  FastAPI   │
        └──────────┘  └────────────┘  └────────────┘  └─────┬──────┘
                       geometrie       potwierdzenie         │
                       budynków        azbestu               ▼
                                                      kafelki satelitarne
                                                      + model ONNX
```

**Kluczowa decyzja:** MySQL jest cache'em, nie tylko magazynem. Pierwszy skan obszaru trwa
5–15 s (trzy zewnętrzne API), każdy kolejny tego samego obszaru — poniżej 100 ms.

---

## 3. Stack (nie zmieniaj bez pytania)

| Warstwa | Technologia |
|---|---|
| Monorepo | pnpm workspaces |
| Backend | Node.js 20 + Express + TypeScript |
| ORM / DB | Prisma + MySQL 8 |
| Walidacja HTTP | Zod (tylko request/response — **nie** duplikuj typów encji) |
| Kontrakt API | OpenAPI 3.0 (`spec/openapi.yaml`) |
| Frontend | Next.js (App Router) + React Query + Tailwind |
| Mapa | Leaflet + react-leaflet + leaflet-draw |
| Wykresy / PDF | Recharts, jsPDF + jspdf-autotable |
| Klient API | hey-api (`@hey-api/openapi-ts`) — generowany z openapi.yaml |
| ML serving | Python + FastAPI + ONNX Runtime |
| ML trening | PyTorch (osobno, poza aplikacją) |
| Deploy | Docker Compose (3 usługi + MySQL) |

**Zasada typów:** `Prisma Client` = źródło prawdy dla encji. `Zod` = wyłącznie walidacja HTTP.
Frontend używa typów z wygenerowanego klienta hey-api. Żadnych ręcznie pisanych interfejsów `Building`.

---

## 4. Struktura repozytorium

```
.
├── spec/
│   ├── openapi.yaml          # kontrakt API — źródło prawdy dla frontendu
│   └── domain.json           # model domenowy
├── packages/
│   ├── database/             # Prisma schema + klient + migracje
│   ├── validation/           # schematy Zod (requests.ts, responses.ts)
│   ├── asbestos-checker/     # biblioteka: sprawdzanie WMS Bazy Azbestowej
│   ├── backend/              # Express API
│   │   └── src/{routes,controllers,services,middleware}
│   └── frontend/             # Next.js
│       └── src/{app,components,features/map,lib/api}
├── api/                      # serwis ML (FastAPI + ONNX)
├── ml/                       # notebooki treningowe, przygotowanie datasetu
├── artifacts/                # wytrenowany model .onnx
└── docker/                   # Dockerfile'e + docker-compose
```

---

## 5. Model danych

Jedna tabela. Celowo — to hackathon, nie system ewidencji.

```prisma
model Building {
  id                    String   @id @default(cuid())
  polygon               Json     // [[lng, lat], [lng, lat], ...]
  centroidLng           Float
  centroidLat           Float
  isAsbestos            Boolean  @default(false)  // z oficjalnej bazy
  isPotentiallyAsbestos Boolean?                  // z ML; null = nie sprawdzono
  createdAt             DateTime @default(now())
  updatedAt             DateTime @updatedAt

  @@index([centroidLng, centroidLat])   // zapytania po bbox
  @@index([isAsbestos])
  @@index([isPotentiallyAsbestos])
}
```

**Trzy stany, nie dwa.** `isPotentiallyAsbestos` musi być nullowalne — gdy serwis ML nie odpowie,
zapisujemy `null` (nieznane), a nie `false` (czysty). Kłamanie o wyniku jest gorsze niż jego brak.

**Deduplikacja:** budynek uznajemy za ten sam, jeśli centroid mieści się w ±0.0001° (~11 m).
OSM zmienia ID przy edycji geometrii, więc nie da się polegać na `osm_id`.

---

## 6. Kontrakt API

Wszystkie odpowiedzi mają jednolity kształt:

```ts
{ data: T | null, error: { message: string, code: string } | null }
```

| Endpoint | Opis |
|---|---|
| `POST /api/bbox` | `{ ne: {lat,lng}, sw: {lat,lng} }` → `{ buildings: Building[], stats: BBoxStats }` |
| `GET /api/buildings/:id` | pojedynczy budynek |
| `GET /api/geocode?query=` | adres → współrzędne (podpowiedzi do wyszukiwarki) |
| `POST /api/geocode/batch` | współrzędne → adresy (do 1000 naraz) |
| `GET /health` | health check dla Dockera |

```ts
type Building = {
  id: string
  polygon: number[][]            // pary [lng, lat] — UWAGA: Leaflet chce [lat, lng]
  centroid: { lng: number; lat: number }
  isAsbestos: boolean
  isPotentiallyAsbestos: boolean | null
  createdAt: string
  updatedAt: string
}

type BBoxStats = {
  total: number
  asbestos: number               // potwierdzone w bazie
  potentiallyAsbestos: number    // tylko ML, bez potwierdzenia
  clean: number                  // sprawdzone, bez azbestu
  unknown: number                // ML nie odpowiedział
}
```

**Limit obszaru:** bbox walidowany po obu stronach — maksymalnie `0.0005 deg²` (~2 × 2 km).
Ta sama stała musi być użyta na froncie i w backendzie (import z `packages/validation`),
inaczej frontend przepuszcza request, który backend odrzuca z 400.

---

## 7. Integracje zewnętrzne

### 7.1 Overpass API (geometrie budynków)
`https://overpass-api.de/api/interpreter`, zapytanie Overpass QL:

```
[out:json];
(
  way["building"](south,west,north,east);
  relation["building"](south,west,north,east);
);
out geom;
```

Publiczna instancja ma rate limiting i potrafi zwrócić 429/504. Timeout 30 s, obsłuż błąd
czytelnym komunikatem. Na demo warto mieć drugą instancję jako fallback.

### 7.2 Baza Azbestowa — WMS (potwierdzenie)
`https://esip.bazaazbestowa.gov.pl/GeoServerProxy`, warstwa `budynki_z_azbestem`.

Nie ma API zwracającego dane — jest tylko serwis mapowy zwracający **obrazek**. Trik:

1. Policz bbox budynku + 20% marginesu, wymuś kwadrat (WMS tego wymaga).
2. Pobierz kafelek PNG 256×256 (`SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&SRS=EPSG:4326`).
3. Przejedź piksele; szukaj koloru `#2c8900` z tolerancją 10 (odległość euklidesowa w RGB).
4. Przelicz pozycję pasującego piksela z powrotem na lat/lng (pamiętaj o odwróceniu osi Y).
5. Sprawdź ray-castingiem, czy punkt leży **wewnątrz** wielokąta budynku.
6. Znaleziony choć jeden piksel → `isAsbestos = true`.

Przetwarzanie równoległe: ~20 jednoczesnych żądań. To jest wąskie gardło skanu.

### 7.3 Mapbox Geocoding
Forward geocoding do wyszukiwarki (limit do `countries=pl`) i Batch API v6 do adresów budynków
(max 50 współrzędnych na żądanie — dziel na paczki). Token w zmiennej środowiskowej.

### 7.4 Serwis ML (predykcja)
`POST /batch_predict` → `{ coordinates: [{ centroidLat, centroidLng, id? }] }`
→ `{ results: [{ id, isPotentiallyAsbestos: float, success, error? }], total, successful, failed }`

Backend zamienia prawdopodobieństwo na boolean progiem **0.7**. Timeout 30 s; przy błędzie
całe zapytanie zwraca `null` dla każdego budynku i aplikacja działa dalej.

---

## 8. Pipeline ML

**Dane treningowe:** dla każdego budynku z OSM pobierz kafelek satelitarny wycentrowany na
centroidzie (zoom 20, wycinek 100–128 px). Etykietę weź z Bazy Azbestowej (mechanizm z 7.2) —
czyli oficjalna baza służy jako automatyczny labeler. To daje kilka tysięcy przykładów bez
ręcznego opisywania. Zbalansuj klasy, podziel 80/10/10 ze stratyfikacją.

**Model:** CNN z blokami typu Inception (gałęzie 1×1, 3×3, 5×5 + max-pool, konkatenacja),
4 bloki, dropout 0.55, dwie warstwy gęste 1024, wyjście binarne. Adam, lr 0.0015, ~128 epok,
standaryzacja per obraz (radzi sobie z różnym oświetleniem kafelków).

**Serving:** eksport do ONNX, `onnxruntime` w FastAPI. Normalizacja musi używać **dokładnie tych
samych** mean/std co trening — zapisz je razem z modelem, nie przepisuj ręcznie.

**Uczciwość wyniku:** model nie „wykrywa azbestu”, tylko rozpoznaje faliste, szare pokrycie dachu
typowe dla eternitu. Nazywaj to w UI „podejrzenie”, nigdy „wykryto”. Podaj metryki (accuracy,
precision, recall, F1) i przyznaj, że etykiety z Bazy Azbestowej same są niepełne.

---

## 9. Zasady pracy dla agenta

1. **Kolejność jest ważna:** schema Prisma → OpenAPI → Zod → backend → generowany klient → frontend.
   Kontrakt powstaje przed implementacją, nie po.
2. **Nigdy nie pisz ręcznie typów API na froncie** — regeneruj klienta z `openapi.yaml`.
3. **Każda integracja zewnętrzna ma fallback.** Padnięty Overpass/WMS/ML nie może wywalić całej
   odpowiedzi — loguj, zwracaj `null`/`false` i leć dalej.
4. **Żadnych kluczy API w kodzie.** Tylko `process.env` + `.env.example`.
5. **Komunikaty dla użytkownika po polsku i konkretne** („Obszar za duży — zaznacz maks. 2 × 2 km”),
   nie „Something went wrong”.
6. Po każdej fazie: uruchom build, usuń `console.log` i nieużywane importy.
7. Nie dodawaj bibliotek spoza sekcji 3 bez pytania.

---

## 10. Fazy kodowania

Każda faza kończy się czymś działającym. Nie zaczynaj kolejnej, zanim „Gotowe, gdy” nie jest prawdą.
Prompt startowy dla każdej z nich znajdziesz w `PHASES.md`.

| Faza | Zakres | Zależy od |
|---|---|---|
| F0 | Fundament monorepo + MySQL | — |
| F1 | Schema Prisma, OpenAPI, Zod, klient | F0 |
| F2 | Szkielet backendu i middleware | F1 |
| F3 | Mock `/bbox` + mapa Leaflet | F2 |
| F4 | Rysowanie bbox + pobieranie danych | F3 |
| F5 | Kolorowanie, popupy, legenda | F4 |
| F6 | Overpass API + cache w MySQL | F2, F5 |
| F7 | Baza Azbestowa (WMS) | F6 |
| F8 | Serwis ML (FastAPI + ONNX) | F6 |
| F9 | Statystyki, wykres, PDF | F5 |
| F10 | Dopracowanie + Docker | wszystkie |

F6 i F7/F8 da się prowadzić równolegle z F9, jeśli pracujesz w zespole — frontend od F5 nie zależy już od tego, skąd biorą się dane.

### F0 — Fundament
Monorepo pnpm, 4 paczki, `docker-compose.yml` z MySQL, tsconfig, eslint, `.env.example`.
**Gotowe, gdy:** `pnpm install` przechodzi, MySQL wstaje, `pnpm build` nie sypie błędami.

### F1 — Kontrakt i model danych
Schema Prisma + migracja, `spec/openapi.yaml` z pełnymi schematami, schematy Zod w `packages/validation`
(w tym walidacja wielkości bbox), generacja klienta hey-api.
**Gotowe, gdy:** `prisma migrate` tworzy tabelę, klient TS generuje się bez błędów.

### F2 — Szkielet backendu
Express + CORS + `express.json`, middleware: `validate` (Zod), `asyncHandler`, `errorHandler`,
`sendSuccess`/`sendError`, `/health`, routing.
**Gotowe, gdy:** `GET /health` odpowiada, błędna treść na `POST /bbox` daje 400 z listą błędów Zod.

### F3 — Mock API i frontend bazowy
Endpoint `/bbox` zwracający wygenerowane losowe budynki (z opóźnieniem 1,5 s).
Next.js: layout z QueryClientProvider i Toasterem, mapa Leaflet przez `dynamic(..., { ssr: false })`,
dwie warstwy podkładowe, kontrolka zoomu.
**Gotowe, gdy:** mapa renderuje się w przeglądarce, bez błędów SSR.

### F4 — Zaznaczanie obszaru i pobieranie danych
`RectangleDrawer` (leaflet-draw, walidacja wielkości, blokada w trakcie ładowania, czyszczenie),
hook `useBBoxBuildings` (React Query `useMutation`), kumulowanie wyników z deduplikacją po `id`,
loader i toasty.
**Gotowe, gdy:** narysowanie prostokąta pokazuje budynki z mocka; drugi obszar dokłada się do pierwszego.

### F5 — Wizualizacja
Wielokąty z kolorowaniem (czerwony `#EF4444` / pomarańczowy `#F59E0B` / zielony `#10B981` /
szary `#6B7280`), popupy ze szczegółami, legenda, panel instrukcji dla nowego użytkownika.
**Uwaga:** API daje `[lng, lat]`, Leaflet chce `[lat, lng]`.
**Gotowe, gdy:** mapa wygląda jak produkt i da się ją pokazać na demo.

### F6 — Prawdziwe dane: Overpass
`OverpassService` (zapytanie QL, konwersja na polygon, centroid), podmiana mocka w `/bbox`,
zapis i odczyt z MySQL z deduplikacją po centroidzie.
**Gotowe, gdy:** widzisz prawdziwe budynki; drugi skan tego samego obszaru wraca z bazy poniżej 100 ms.

### F7 — Baza Azbestowa
`packages/asbestos-checker`: pobieranie kafelka WMS, analiza pikseli, point-in-polygon,
batch z kontrolą współbieżności (20). Podpięcie w `/bbox`.
**Gotowe, gdy:** budynki zgłoszone w oficjalnej bazie świecą się na czerwono — sprawdź na obszarze,
o którym wiesz, że coś tam jest.

### F8 — Serwis ML
FastAPI: pobieranie kafelków satelitarnych (async, sesja aiohttp z poolingiem), preprocessing,
ONNX Runtime, `/predict` i `/batch_predict` z semaforem i batchowaniem inferencji, `/health`.
Backend: `MLService` z progiem 0.7 i degradacją do `null`.
**Gotowe, gdy:** budynki bez potwierdzenia dostają pomarańczowy kolor od modelu, a wyłączenie
serwisu ML nie psuje skanu (wszystko robi się szare).

### F9 — Raport i statystyki
Panel statystyk liczony z tablicy budynków (`useMemo`), wykres kołowy (Recharts),
eksport PDF (jsPDF + autoTable) z osadzonym fontem dla polskich znaków, numeracja stron.
**Gotowe, gdy:** PDF otwiera się poprawnie i ma „ł”, „ę”, „ż”.

### F10 — Dopracowanie i deploy
Filtry kategorii, responsywność, dostępność, `memo`/`useMemo` na liście wielokątów lub
`preferCanvas`, Dockerfile'e (backend / frontend `output: 'standalone'` / ML), `docker-compose-prod.yml`,
README z instrukcją uruchomienia.
**Gotowe, gdy:** `docker compose up` stawia całość na czystej maszynie.

---

## 11. Znane pułapki

| Pułapka | Objaw | Rozwiązanie |
|---|---|---|
| `[lng, lat]` vs `[lat, lng]` | budynki lądują w Somalii albo na Bałtyku | jedna funkcja konwertująca, użyta wszędzie |
| Leaflet w SSR | `window is not defined` przy buildzie | `dynamic(..., { ssr: false })` |
| Mutacja stanu (`splice` na tablicy ze stanu) | budynki znikają przy szybkich skanach | `slice` / nowa tablica |
| Dopasowywanie adresów po indeksie | adresy trafiają do złych budynków | mapa `id → adres` |
| Dwie różne stałe limitu bbox | frontend wysyła, backend odrzuca z 400 | jedna stała w `packages/validation` |
| Statystyki w osobnym stanie | panel, mapa i PDF pokazują różne liczby | licz z tablicy budynków w `useMemo` |
| Domyślne fonty jsPDF | raport bez polskich znaków | osadzony font TTF w repo, nie z CDN |
| `NEXT_PUBLIC_*` w obrazie Dockera | aplikacja strzela do `localhost` po deployu | przekaż jako build arg przy `next build` |
| `null` zapisywane jako `false` | „czysty” budynek, którego nikt nie sprawdził | trzy stany, nie dwa |
| z-index Leafleta | panele chowają się pod mapą | panele `z-[1000]`, elementy przy kontrolkach `z-[500]` |

---

## 12. Kryterium sukcesu (demo)

Urzędnik wpisuje nazwę miejscowości, zaznacza kwartał zabudowy, po kilku sekundach widzi
kolorową mapę, klika budynek i widzi jego adres, a na końcu pobiera PDF z listą i statystykami.
Drugie zaznaczenie tego samego obszaru jest natychmiastowe.

Na demo przygotuj wcześniej obszar z **mieszanym** wynikiem — trochę czerwonych, trochę
pomarańczowych, reszta zielona. Obszar w samych zielonych nie pokazuje niczego.
