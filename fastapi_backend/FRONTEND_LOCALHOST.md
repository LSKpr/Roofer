# Frontend: użycie Roofer API przez localhost

Ten plik jest krótką instrukcją dla osoby implementującej frontend. Backend wykonuje obliczenia na serwerze, ale dzięki tunelowi SSH frontend wywołuje go pod lokalnym adresem:

```text
http://127.0.0.1:8001
```

Pełna dokumentacja backendu znajduje się w `fastapi_backend/README.md`.

## 1. Uruchom tunel SSH

Otwórz osobny terminal i pozostaw go uruchomionego przez cały czas pracy z frontendem:

```bash
ssh -N -L 127.0.0.1:8001:127.0.0.1:8000 student@54.209.243.78
```

Polecenie może nie wyświetlać żadnego komunikatu — to prawidłowe zachowanie. Przekazuje ono lokalny port `8001` do backendu działającego na serwerze.

Jeśli lokalny port `8001` jest zajęty, użyj innego, np. `8010`:

```bash
ssh -N -L 127.0.0.1:8010:127.0.0.1:8000 student@54.209.243.78
```

Wtedy zmień adres API na `http://127.0.0.1:8010`.

## 2. Sprawdź połączenie

Otwórz w przeglądarce:

```text
http://127.0.0.1:8001/health
```

Dokumentacja Swagger:

```text
http://127.0.0.1:8001/docs
```

Można również sprawdzić połączenie w terminalu:

```bash
curl --fail http://127.0.0.1:8001/health
```

Jeśli połączenie nie działa:

1. sprawdź, czy terminal z tunelem SSH nadal działa;
2. sprawdź, czy możesz zalogować się przez `ssh student@54.209.243.78`;
3. na serwerze sprawdź `curl http://127.0.0.1:8000/health`;
4. pamiętaj, że ta tymczasowa instancja ma zostać wyłączona 20 września 2026 o 18:20 UTC.

## 3. Pobierz token

Endpoint analizy wymaga tokenu. Odczytaj go przez SSH i przechowuj tylko lokalnie:

```bash
ssh student@54.209.243.78 'cat ~/model_final/fastapi_backend/runtime/api-token'
```

Nie commituj tokenu, nie wklejaj go do publicznego repozytorium i nie zapisuj w logach. Do lokalnego developmentu możesz umieścić go w pliku `.env.local`, który musi być ignorowany przez Git.

Przykład dla Vite:

```dotenv
VITE_ROOFER_API_URL=http://127.0.0.1:8001
VITE_ROOFER_API_TOKEN=TU_WKLEJ_TOKEN
```

Przykład dla Next.js uruchamianego lokalnie:

```dotenv
NEXT_PUBLIC_ROOFER_API_URL=http://127.0.0.1:8001
NEXT_PUBLIC_ROOFER_API_TOKEN=TU_WKLEJ_TOKEN
```

Zmienne `VITE_*` i `NEXT_PUBLIC_*` są widoczne w kodzie przeglądarki. Jest to akceptowalne wyłącznie dla lokalnego prototypu. W publicznej aplikacji wywołuj Roofer API przez własny backend/proxy i nie ujawniaj tokenu w bundle frontendu.

## 4. Endpoint

```text
POST /v1/analyze
```

Pełny URL lokalny:

```text
http://127.0.0.1:8001/v1/analyze
```

Nagłówki:

```http
Authorization: Bearer TOKEN
Content-Type: application/json
```

Body:

```json
{
  "south_west": {
    "longitude": 21.0274,
    "latitude": 52.0736
  },
  "north_east": {
    "longitude": 21.0283,
    "latitude": 52.0739
  }
}
```

Współrzędne są w WGS84 / EPSG:4326:

- `south_west` — lewy dolny róg prostokąta;
- `north_east` — prawy górny róg;
- `longitude` — długość geograficzna (`lng`);
- `latitude` — szerokość geograficzna (`lat`).

## 5. Gotowa funkcja TypeScript

```ts
export type RooferPoint = {
  longitude: number;
  latitude: number;
};

export type RooferStatus =
  | 'ok'
  | 'low_quality'
  | 'imagery_error'
  | 'geometry_error';

export type RooferFeature = {
  type: 'Feature';
  id: string;
  geometry: {
    type: 'Polygon' | 'MultiPolygon';
    coordinates: unknown[];
  };
  properties: {
    building_id: string;
    source_id: string;
    building_type: string | null;
    status: RooferStatus;
    asbestos_probability: number | null;
    roof_center: RooferPoint | null;
    quality: Record<string, number | string | null> | null;
    reasons: string[];
  };
};

export type RooferResponse = {
  type: 'FeatureCollection';
  bbox: [number, number, number, number];
  features: RooferFeature[];
  meta: {
    matched: number;
    predicted: number;
    low_quality: number;
    errors: number;
    model_id: string;
    elapsed_seconds: number;
    building_source: string;
    attribution: string;
    warning: string;
  };
};

export async function analyzeRoofs(params: {
  southWest: RooferPoint;
  northEast: RooferPoint;
  token: string;
  apiUrl?: string;
  signal?: AbortSignal;
}): Promise<RooferResponse> {
  const apiUrl = params.apiUrl ?? 'http://127.0.0.1:8001';
  const timeout = AbortSignal.timeout(195_000);
  const signal = params.signal
    ? AbortSignal.any([params.signal, timeout])
    : timeout;

  const response = await fetch(`${apiUrl}/v1/analyze`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${params.token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      south_west: params.southWest,
      north_east: params.northEast,
    }),
    signal,
  });

  const body = await response.json();

  if (!response.ok) {
    const code = body?.detail?.code ?? `HTTP_${response.status}`;
    const error = new Error(code);
    Object.assign(error, {
      status: response.status,
      retryAfter: response.headers.get('Retry-After'),
      body,
    });
    throw error;
  }

  return body as RooferResponse;
}
```

`AbortSignal.any` wymaga współczesnej przeglądarki. Jeśli projekt wspiera starsze środowiska, użyj jednego przekazanego sygnału lub własnego `AbortController`.

## 6. Użycie z Leaflet

```ts
const southWest = map.getBounds().getSouthWest();
const northEast = map.getBounds().getNorthEast();

const result = await analyzeRoofs({
  southWest: {
    longitude: southWest.lng,
    latitude: southWest.lat,
  },
  northEast: {
    longitude: northEast.lng,
    latitude: northEast.lat,
  },
  token: import.meta.env.VITE_ROOFER_API_TOKEN,
  apiUrl: import.meta.env.VITE_ROOFER_API_URL,
});

L.geoJSON(result, {
  style: (feature) => {
    const properties = feature?.properties;

    if (properties?.status !== 'ok') {
      return { color: '#6b7280', fillColor: '#9ca3af', fillOpacity: 0.35 };
    }

    const probability = properties.asbestos_probability ?? 0;
    const color = probability >= 0.7
      ? '#dc2626'
      : probability >= 0.4
        ? '#f59e0b'
        : '#16a34a';

    return { color, fillColor: color, fillOpacity: 0.55 };
  },
  onEachFeature: (feature, layer) => {
    const properties = feature.properties;
    const score = properties.asbestos_probability == null
      ? 'brak wyniku'
      : `${(properties.asbestos_probability * 100).toFixed(1)}%`;

    layer.bindPopup(`
      <strong>Budynek ${properties.source_id}</strong><br />
      Status: ${properties.status}<br />
      Wynik modelu: ${score}<br />
      ${properties.reasons.length ? `Powody: ${properties.reasons.join(', ')}` : ''}
    `);
  },
}).addTo(map);
```

GeoJSON zapisuje pozycje jako `[longitude, latitude]`. `L.geoJSON` rozumie tę kolejność automatycznie. Nie zamieniaj ręcznie współrzędnych geometrii. Przy pobieraniu granic Leaflet używaj odpowiednio `.lng` i `.lat`, jak w przykładzie.

## 7. Interpretacja wyników

Każdy znaleziony budynek pozostaje w odpowiedzi, również gdy nie udało się uzyskać predykcji.

| `status` | `asbestos_probability` | Zachowanie frontendu |
|---|---:|---|
| `ok` | liczba 0–1 | Pokaż kolor/skorę modelu. |
| `low_quality` | `null` | Pokaż neutralny kolor i powody z `reasons`. |
| `imagery_error` | `null` | Pokaż błąd tymczasowy; można umożliwić ponowienie. |
| `geometry_error` | `null` | Pokaż brak możliwości analizy geometrii. |

Nie zamieniaj `null` na `0`. `null` oznacza brak wiarygodnej predykcji, a nie brak azbestu.

Wynik modelu nie jest potwierdzeniem obecności ani braku azbestu. Interfejs powinien wyświetlać informację z `meta.warning` i atrybucję z `meta.attribution`.

## 8. Limity i błędy HTTP

Domyślne limity jednego żądania:

- maksymalnie 4 km²;
- maksymalnie 100 budynków;
- jedno aktywne zapytanie analizy;
- 10 prób analizy na minutę;
- timeout około 180 sekund.

| HTTP | Kod | Co zrobić |
|---:|---|---|
| 401 | `UNAUTHORIZED` | Sprawdź token. |
| 408 | `BODY_TIMEOUT` | Wyślij żądanie ponownie. |
| 413 | `AREA_TOO_LARGE` | Zmniejsz widoczny prostokąt. |
| 413 | `TOO_MANY_BUILDINGS` | Podziel obszar na mniejsze prostokąty. |
| 413 | `BODY_TOO_LARGE` | Nie wysyłaj dodatkowych danych w body. |
| 422 | walidacja | Sprawdź kolejność rogów i zakres współrzędnych. |
| 429 | `BUSY` | Poczekaj zgodnie z `Retry-After`. |
| 429 | `RATE_LIMITED` | Poczekaj zgodnie z `Retry-After`. |
| 504 | `ANALYSIS_TIMEOUT` | Zmniejsz prostokąt lub ponów później. |

Backend nie ucina po cichu listy do 100 elementów. Przy dzieleniu obszaru na kafelki ten sam budynek może wystąpić w kilku odpowiedziach — deduplikuj wynik po `feature.id`.

## 9. Zalecany przepływ UI

1. Użytkownik przesuwa mapę.
2. Frontend nie wysyła żądania przy każdym pikselu ruchu.
3. Użytkownik klika „Analizuj widoczny obszar” albo frontend stosuje debounce.
4. Pokaż spinner; analiza może wymagać pobrania wielu zdjęć.
5. Po odpowiedzi dodaj `FeatureCollection` jako warstwę GeoJSON.
6. Poligony ze statusem innym niż `ok` pokaż neutralnym kolorem.
7. Wyświetl `meta.matched`, `meta.predicted`, `meta.low_quality`, `meta.errors`, `meta.warning` oraz `meta.attribution`.
8. Przy zmianie obszaru anuluj poprzedni `fetch`, ale nie zakładaj, że natychmiast zwolni to serwer — jeśli otrzymasz `BUSY`, odczekaj i ponów.
