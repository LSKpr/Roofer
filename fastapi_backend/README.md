# Roofer — API dla frontendu

Backend wyszukuje budynki przecinające prostokąt, pobiera wycinki ich dachów z Google Satellite i oblicza wynik modelu azbestu. Odpowiedź to GeoJSON `FeatureCollection`, gotowa do użycia w Leaflet/MapLibre.

Dla osoby implementującej frontend przygotowano krótszą instrukcję krok po kroku: [`FRONTEND_LOCALHOST.md`](FRONTEND_LOCALHOST.md).

## Adres i dostęp

- Backend jest uruchomiony na `0.0.0.0:8000` na serwerze. Adres docelowy: `http://54.209.243.78:8000`.
- **Stan sprawdzony 20 września 2026:** `/health` oraz rzeczywista analiza działają na serwerze i przez tunel SSH. Bezpośrednie połączenie z tego Maca do publicznego portu 8000 kończy się timeoutem; potrzebna jest konfiguracja sieci/Security Group przez administratora. Do tego czasu używaj tunelu opisanego poniżej.
- Swagger UI: `/docs`, OpenAPI: `/openapi.json`.
- Lokalnie: `http://127.0.0.1:8001`.
- Kod na serwerze: `/home/student/model_final/fastapi_backend`.
- `POST /v1/analyze` wymaga `Authorization: Bearer <TOKEN>`.
- Token znajduje się w `fastapi_backend/runtime/api-token`. Nie jest umieszczony w README ani logach. Przekaż go koledze prywatnym kanałem; nie publikuj go w Git. `/health` i dokumentacja nie wymagają tokenu.
- To instancja tymczasowa: według informacji z jej uruchomienia kończy działanie **20 września 2026 o 18:20 UTC**. Lokalna kopia backendu, bazy i modelu pozwala odtworzyć usługę na innym serwerze.

**HTTP nie szyfruje tokenu. Do dostępu poza zaufaną siecią użyj HTTPS przez reverse proxy lub tunelu SSH.** Publiczny frontend HTTPS nie może bezpośrednio wywoływać API HTTP z powodu mixed content. Stały token wpisany do kodu przeglądarkowego jest widoczny dla użytkownika: do publicznego wdrożenia użyj własnego backendu pośredniczącego i uwierzytelniania użytkowników.

Tunel, jeśli masz uprawnienia SSH do serwera:

```bash
ssh -N -L 8001:127.0.0.1:8000 student@54.209.243.78
```

Wtedy frontend używa `http://127.0.0.1:8001`. Każdy komputer potrzebuje własnego dostępu SSH; nie kopiuj klucza prywatnego innej osoby.

## Endpoint: POST /v1/analyze

Współrzędne **WGS84 / EPSG:4326**. `south_west` to lewy dolny róg, `north_east` to prawy górny. `longitude` oznacza długość, `latitude` szerokość geograficzną. Nie używaj współrzędnych EPSG:3857 ani pikseli mapy.

```json
{
  "south_west": {"longitude": 21.0274, "latitude": 52.0736},
  "north_east": {"longitude": 21.0283, "latitude": 52.0739}
}
```

```bash
export ROOFER_API_TOKEN="$(cat fastapi_backend/runtime/api-token)"
curl --fail-with-body http://127.0.0.1:8001/v1/analyze \
  -H "Authorization: Bearer $ROOFER_API_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"south_west":{"longitude":21.0274,"latitude":52.0736},"north_east":{"longitude":21.0283,"latitude":52.0739}}'
unset ROOFER_API_TOKEN
```

Nie używaj `curl -v` ani debugowania nagłówków z prawdziwym tokenem. Dla szyfrowanego dostępu lokalny port 8001 powinien pochodzić z tunelu SSH.

### Odpowiedź

Przykład struktury, nie rzeczywista predykcja dla poniższego budynku:

```json
{
  "type": "FeatureCollection",
  "bbox": [21.0274, 52.0736, 21.0283, 52.0739],
  "features": [
    {
      "type": "Feature",
      "id": "osm:2",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[21.0275,52.0737],[21.0277,52.0737],[21.0277,52.0738],[21.0275,52.0738],[21.0275,52.0737]]]
      },
      "properties": {
        "building_id": "osm:2",
        "source_id": "5857806",
        "building_type": "city_hall",
        "status": "ok",
        "asbestos_probability": 0.72,
        "roof_center": {"longitude": 21.0276, "latitude": 52.07375},
        "quality": {
          "roof_fraction": 0.7,
          "green_fraction": 0.03,
          "roof_green_fraction": 0.01,
          "sharpness": 150.0,
          "contrast": 32.0,
          "edge_density": 0.12,
          "region_source": "footprint"
        },
        "reasons": []
      }
    }
  ],
  "meta": {
    "matched": 1,
    "predicted": 1,
    "low_quality": 0,
    "errors": 0,
    "model_id": "sha256-modelu-onnx",
    "elapsed_seconds": 2.1,
    "building_source": "budynki-osm-mazowieckie.geojson",
    "attribution": "© OpenStreetMap contributors, ODbL; imagery: Google Satellite",
    "warning": "Model score is not confirmation of asbestos. Database coverage is limited to the imported OSM snapshot."
  }
}
```

- `geometry` może być `Polygon` **lub** `MultiPolygon`; zachowuje pełny obrys i otwory, nie jest przycinana do prostokąta.
- W GeoJSON kolejność pozycji to **[longitude, latitude]**, inaczej niż typowe tablice Leaflet `[latitude, longitude]`.
- Wybór to dokładne przecięcie poligonu z prostokątem, nie sam centroid i nie tylko przecięcie bounding boxów. Budynki dotykające granicy również są uwzględniane. Środek analizowanego dachu może leżeć poza prostokątem, jeśli budynek przecina jego granicę.
- Dla `MultiPolygon` analiza obrazu dotyczy największej części obrysu. Nie wykonujemy osobnej predykcji każdej części.
- `building_id`/`id` są identyfikatorami w danej wersji lokalnej bazy; `source_id` to identyfikator źródłowy OSM.
- `asbestos_probability` mieści się w `[0, 1]`. Wynik to `softmax(logits)[1]` dla klas `[non_asbestos, asbestos]`, **nie potwierdzenie materiału ani skalibrowana pewność diagnostyczna**.
- `null` nie oznacza `0`, „brak azbestu” ani nieistniejącego budynku.

| `status` | Prawdopodobieństwo | Znaczenie |
|---|---|---|
| `ok` | liczba 0–1 | Zdjęcie przeszło kontrolę jakości i model wykonał predykcję. |
| `low_quality` | `null` | Za mało szczegółów, za dużo zieleni lub zbyt mało obrysu dachu w kadrze. Powody w `reasons`. |
| `imagery_error` | `null` | Kafelek niedostępny, timeout lub niepoprawny obraz. Można ponowić. |
| `geometry_error` | `null` | Nie udało się wyznaczyć punktu wewnątrz dachu. |

Błędy pojedynczych zdjęć nie usuwają poligonów z wyniku. `meta.matched` obejmuje wszystkie zwrócone budynki. Brak budynków daje HTTP 200 z pustą tablicą `features`.

### Frontend — fetch

```javascript
export async function analyzeRoofs(bounds, token, baseUrl = 'http://127.0.0.1:8001') {
  const sw = bounds.getSouthWest();
  const ne = bounds.getNorthEast();
  const response = await fetch(`${baseUrl}/v1/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      south_west: { longitude: sw.lng, latitude: sw.lat },
      north_east: { longitude: ne.lng, latitude: ne.lat },
    }),
    signal: AbortSignal.timeout(195_000),
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail?.code ?? JSON.stringify(body.detail));
  }
  return body;
}
```

Wywołuj po kliknięciu „Analizuj” albo po debouncingu, nie przy każdym ruchu mapy. Oznacz na mapie `null` innym kolorem niż niski wynik. Żądania mogą trwać kilkadziesiąt sekund; cache kafelków przyspiesza kolejne zapytania. Anulowanie `fetch` nie gwarantuje natychmiastowego przerwania obliczeń na serwerze.

### Limity i błędy

Domyślnie: maksymalnie **4 km²**, **100 budynków**, **180 sekund**, jedno aktywne zapytanie analizy i **10 prób analizy/minutę łącznie** dla instancji. Maksymalny JSON request: 8 KiB. Nie zwracamy po cichu pierwszych 100 budynków: większy wynik dostaje 413. Zmniejsz prostokąt lub podziel go na mniejsze; deduplikuj budynki według `id` na granicach kafelków.

| HTTP | Znaczenie |
|---|---|
| 401 | Brak/poprawność tokenu; sprawdź Bearer Authorization. |
| 408 | Nie udało się odebrać body w 10 sekund. |
| 413 | `AREA_TOO_LARGE`, `TOO_MANY_BUILDINGS` lub `BODY_TOO_LARGE`. |
| 422 | Błędne współrzędne, odwrócone rogi, dodatkowe pola lub niepoprawny JSON. |
| 429 | `BUSY` lub `RATE_LIMITED`; respektuj nagłówek `Retry-After`. |
| 504 | `ANALYSIS_TIMEOUT`; zmniejsz obszar lub spróbuj ponownie później. |
| 500 | Nieoczekiwany błąd usługi; administrator powinien sprawdzić log. |

## Dane i preprocessing

Baza zawiera **2 585 219 obrysów budynków OSM z Mazowsza**, nie listę potwierdzonych domów mieszkalnych. Obejmuje też garaże, budynki gospodarcze i inne typy. Poza zakresem snapshotu odpowiedź może być pusta — nie jest to dowód braku zabudowy.

SQLite zawiera WKB poligonów, R-tree i metadane; aplikacja otwiera ją tylko do odczytu. Aktualizacje wymagają zbudowania nowego pliku i restartu z jego ścieżką, nie nadpisywania aktywnej bazy.

Obraz: Google Satellite `lyrs=s`, zoom 20, dziewięć kafelków 256×256, wycinek 128×128 centrowany na budynku, bez zmniejszania dużych dachów. Centrowanie i kontrola jakości są współdzielone z `Data/build_roof_dataset.py`, aby nie rozchodziły się z przygotowaniem danych. Nie zapisujemy zdjęć na dysku; cache skompresowanych kafelków w RAM ma limit 32 MiB i TTL 1 godzina.

Kontrola jakości: minimalna ostrość 40, kontrast 8, udział krawędzi 0.02, maksymalna zieleń 0.65 całego obrazu / 0.35 nad dachem i minimum 0.15 pokrycia obrysem. To heurystyka, nie gwarantowany detektor dachów. Może odrzucać poprawne zielone/jednolite dachy lub przepuszczać puste działki z nieaktualnym obrysem.

ONNX działa na CPU. Normalizacja jest odczytywana z metadanych modelu: RGB / 255, mean `[0.3616, 0.3497, 0.3882]`, std `[0.2406, 0.2315, 0.2276]`. Używany checkpoint pochodzi z epoki 24 treningu `quality_v2` na serwerze. Wynik testowy modelu: accuracy 77.33%, recall azbestu 62.67%; nie używaj go jako samodzielnego potwierdzenia obecności/braku azbestu. Korzystanie z kafelków musi być zgodne z warunkami dostawcy.

## Uruchomienie lokalne

Wymagany Python **3.11+**, przetestowano 3.13. Wykonuj komendy z katalogu głównego Roofer, **nie** z `fastapi_backend/`. Backend nie jest samodzielną paczką: potrzebuje również współdzielonego `Data/build_roof_dataset.py`, `Data/requirements-dataset.txt` oraz modelu ONNX. Nie wymaga PyTorch, datasetu treningowego ani plików GeoJSON po zbudowaniu bazy.

```bash
python3.13 -m venv /tmp/roofer-api-venv
/tmp/roofer-api-venv/bin/python -m pip install -r fastapi_backend/requirements.txt
/tmp/roofer-api-venv/bin/python -m unittest discover -s fastapi_backend/tests -v
```

Baza i token są już przygotowane w lokalnej kopii. Na nowym środowisku, tylko gdy pliki jeszcze nie istnieją:

```bash
/tmp/roofer-api-venv/bin/python -m fastapi_backend.manage build-db \
  --source Data/budynki-osm-mazowieckie.geojson \
  --output fastapi_backend/data/buildings.sqlite
/tmp/roofer-api-venv/bin/python -m fastapi_backend.manage create-token
```

Obie operacje odmawiają nadpisania istniejącego pliku. Import jest strumieniowy; nie wczytuje całego GeoJSON do RAM. Błędne geometrie są liczone w metadanych jako `skipped_invalid` (dla obecnego snapshotu: 0).

```bash
/tmp/roofer-api-venv/bin/python -m uvicorn fastapi_backend.app:app \
  --host 127.0.0.1 --port 8001 --workers 1 --no-proxy-headers
```

## Konfiguracja

Zmienne środowiskowe odczytywane przy starcie:

| Zmienna | Domyślnie |
|---|---|
| `ROOFER_DATABASE_PATH` | `<repo>/fastapi_backend/data/buildings.sqlite` |
| `ROOFER_MODEL_PATH` | `<repo>/artifacts/roof_classifier_quality_v2_server/model.onnx` |
| `ROOFER_TOKEN_FILE` | `<repo>/fastapi_backend/runtime/api-token` |
| `ROOFER_CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` |
| `ROOFER_MAX_BUILDINGS` | `100` |
| `ROOFER_MAX_AREA_KM2` | `4` |
| `ROOFER_REQUEST_TIMEOUT` | `180` |
| `ROOFER_REQUESTS_PER_MINUTE` | `10` |
| `ROOFER_MODEL_THREADS` | `4` |
| `ROOFER_BATCH_SIZE` | `8` |
| `ROOFER_TILE_CONCURRENCY` | `8` |
| `ROOFER_TILE_TIMEOUT` | `15` |
| `ROOFER_TILE_CACHE_BYTES` | `33554432` |
| `ROOFER_TILE_CACHE_TTL` | `3600` |

CORS przyjmuje listę originów oddzielonych przecinkami, bez ścieżek. Dla tymczasowej integracji można ustawić `ROOFER_CORS_ORIGINS='*'`; cookies/credentials są wyłączone, token nadal obowiązuje. CORS nie jest uwierzytelnianiem ani regułą firewalla.

Używaj jednego procesu Uvicorn: limity i cache są w pamięci procesu. Więcej workerów powiela model oraz limity; skalowanie produkcyjne wymaga wspólnego rate limitera/kolejki.

## Serwer

Środowisko: `/tmp/roofer-api-venv` z Pythonem 3.13. W katalogu `/home/student/model_final`:

```bash
ROOFER_CORS_ORIGINS='*' nohup /tmp/roofer-api-venv/bin/python -m uvicorn \
  fastapi_backend.app:app --host 0.0.0.0 --port 8000 --workers 1 --no-proxy-headers \
  > fastapi_backend/runtime/server.log 2>&1 < /dev/null &
echo $! > fastapi_backend/runtime/server.pid
```

Nie uruchamiaj drugiej kopii, jeśli port 8000 jest zajęty przez działający backend. `nohup` przeżywa rozłączenie SSH, ale nie zapewnia restartu po restarcie maszyny. Interpreter w `/tmp` także wymaga odtworzenia po restarcie; baza i model leżą w katalogu domowym.

```bash
curl --fail http://127.0.0.1:8000/health
tail -f fastapi_backend/runtime/server.log
```

Jeśli `/health` działa wewnątrz serwera, ale z innego komputera jest timeout, administrator powinien dopuścić port TCP 8000 w AWS Security Group/firewallu **dla adresu klienta** albo udostępnić HTTPS/reverse proxy. Nie zmieniaj reguł bezpieczeństwa bez uprawnień. Tunel SSH nie wymaga otwierania nowego portu publicznego.
