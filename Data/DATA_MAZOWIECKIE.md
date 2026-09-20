# Dane budynków w województwie mazowieckim

Ten dokument przekazuje kontekst potrzebny do dalszej pracy z dwoma lokalnymi zbiorami przestrzennymi:

1. wszystkimi poligonami budynków OpenStreetMap w województwie mazowieckim,
2. poligonami obiektów oznaczonych w publicznej warstwie GeoAzbest jako zawierające wyroby azbestowe pozostałe do unieszkodliwienia.

Duże pliki nie są przechowywane bezpośrednio w historii Git. Skompresowane snapshoty powinny być publikowane jako załączniki GitHub Release.

## Snapshot

| Zbiór | Plik lokalny | Liczba obiektów | Rozmiar | Data utworzenia UTC |
| --- | --- | ---: | ---: | --- |
| Wszystkie budynki OSM | `budynki-osm-mazowieckie.geojson` | 2 585 219 | 966 354 855 B (0,90 GiB) | 2026-09-19 21:35:11 |
| Budynki GeoAzbest | `geoazbest-mazowieckie.geojson` | 379 122 | 123 393 269 B (117,68 MiB) | 2026-09-19 20:47:40 |
| Źródłowa paczka OSM | `mazowieckie-latest-free.gpkg.zip` | wiele warstw OSM | 584 122 816 B (557,06 MiB) | zależna od Geofabrik |

Snapshoty mają współrzędne geograficzne WGS 84 w kolejności `[longitude, latitude]`, zgodnej z GeoJSON i EPSG:4326/OGC:CRS84.

## Wszystkie budynki OSM

### Źródło

Regionalny wyciąg Geofabrik:

```text
https://download.geofabrik.de/europe/poland/mazowieckie-latest-free.gpkg.zip
```

Warstwa wejściowa GeoPackage:

```text
gis_osm_buildings_a_free
```

Zbiór obejmuje obiekty OpenStreetMap posiadające tag `building=*`, przekonwertowane przez Geofabrik do warstwy poligonowej. Dane OSM nie są rejestrem urzędowym i mogą zawierać braki, błędy lub nieaktualne obrysy.

Licencja i wymagane oznaczenie:

```text
© OpenStreetMap contributors, ODbL
```

### Format pliku

Plik jest pojedynczym `FeatureCollection`. Konwerter zapisuje geometrie jako `MultiPolygon`, nawet gdy budynek składa się z jednego poligonu.

Przykładowy rekord:

```json
{
  "type": "Feature",
  "id": "5857805",
  "properties": {
    "fid": 1,
    "osm_id": "5857805",
    "code": 1500,
    "fclass": "building",
    "name": "Urząd Dzielnicy Ursynów",
    "type": "city_hall"
  },
  "geometry": {
    "type": "MultiPolygon",
    "coordinates": []
  }
}
```

Znaczenie najważniejszych pól:

- `id` i `properties.osm_id` — identyfikator obiektu OSM dostarczony przez Geofabrik,
- `fid` — lokalny identyfikator rekordu w źródłowym GeoPackage,
- `fclass` — klasa obiektu; dla tej warstwy `building`,
- `type` — wartość tagu opisującego typ budynku, jeśli została podana w OSM,
- `name` — nazwa obiektu, często pusta,
- `code` — kod klasy w schemacie eksportowym Geofabrik,
- `geometry` — obrys budynku w WGS 84.

Nie należy zakładać, że każdy obiekt ma nazwę, typ, wysokość, adres albo liczbę kondygnacji. Darmowy eksport Geofabrik zawiera ograniczony zestaw atrybutów.

### Sposób utworzenia snapshotu

Snapshot został utworzony lokalnym konwerterem Pythona, który odczytał warstwę budynków ze źródłowego GeoPackage, strumieniowo zdekodował geometrie i sprawdził liczbę wyeksportowanych rekordów. Skrypt roboczy nie jest częścią gałęzi publikacyjnej danych.

## Budynki GeoAzbest

### Źródło

Publiczna usługa WFS Bazy Azbestowej:

```text
https://esip.bazaazbestowa.gov.pl/geoserver/wfs/ows
```

Warstwa:

```text
wfs:budynki_z_azbestem
```

Oficjalny opis warstwy: obrysy obiektów budowlanych, w których konstrukcji znalazły się wyroby zawierające azbest pozostałe do unieszkodliwienia.

Snapshot został wybrany filtrem:

```text
nr_dzialki LIKE '14%'
```

Prefiks `14` jest kodem TERYT województwa mazowieckiego.

Publiczna strona Bazy Azbestowej dopuszcza wykorzystanie WFS do analiz przestrzennych, ale nie wskazuje jednoznacznej licencji dla masowej redystrybucji pełnego snapshotu. Przed wykorzystaniem komercyjnym lub dalszą publiczną redystrybucją należy potwierdzić warunki z administracją Bazy Azbestowej i zachować oznaczenie źródła.

### Format pliku

Plik jest pojedynczym `FeatureCollection`. Warstwa źródłowa deklaruje geometrię `Polygon`; downloader akceptuje również `MultiPolygon`.

Przykładowy rekord:

```json
{
  "type": "Feature",
  "id": "budynki_z_azbestem.881351",
  "geometry": {
    "type": "Polygon",
    "coordinates": []
  },
  "geometry_name": "geom_obiektu",
  "properties": {
    "nr_dzialki": "140101_5.0010.269/1"
  }
}
```

Dostępne informacje:

- `id` — identyfikator rekordu WFS GeoAzbest,
- `properties.nr_dzialki` — pełny identyfikator działki ewidencyjnej,
- `geometry` — obrys obiektu w EPSG:4326.

Warstwa publiczna nie udostępnia:

- roku montażu dachu lub wyrobu azbestowego,
- roku dodania wpisu do bazy,
- daty ostatniej aktualizacji obiektu,
- masy ani powierzchni azbestu,
- stopnia pilności,
- właściciela,
- adresu budynku.

Pole `generatedAt` na poziomie kolekcji oznacza datę wykonania lokalnego snapshotu, a nie datę powstania wpisu ani montażu azbestu.

379 122 rekordy nie muszą oznaczać 379 122 unikalnych domów mieszkalnych. Warstwa obejmuje obiekty budowlane, w tym budynki gospodarcze, rolnicze i przemysłowe. Jedna działka może mieć wiele obiektów, a baza może zawierać zduplikowane wpisy lub geometrie.

### Sposób utworzenia snapshotu

Snapshot został utworzony lokalnym downloaderem, który dzieli dane według rozłącznych prefiksów numerów działek, sprawdza liczności podzbiorów, pilnuje unikalności identyfikatorów i dopiero po pełnej walidacji atomowo publikuje plik wynikowy. Skrypt roboczy nie jest częścią gałęzi publikacyjnej danych.

## Łączenie zbiorów

Nie należy łączyć danych wyłącznie po identyfikatorze:

- OSM używa `osm_id`,
- GeoAzbest używa własnego identyfikatora WFS oraz numeru działki,
- nie istnieje wspólny klucz budynku.

Rekomendowany proces dopasowania przestrzennego:

1. zbudować indeks przestrzenny dla obrysów OSM,
2. dla każdego poligonu GeoAzbest znaleźć przecinające się budynki OSM,
3. obliczyć pole przecięcia względem pola obu geometrii,
4. zaakceptować dopasowanie o wysokim pokryciu, np. największym IoU,
5. osobno raportować brak dopasowania, wiele kandydatów oraz identyczne geometrie,
6. nie traktować samego punktu przecięcia jako pewnego dopasowania.

Do takich analiz lepszy jest GeoPackage, GeoParquet lub PostGIS niż prawie gigabajtowy GeoJSON. Do aplikacji webowej należy przygotować PMTiles albo kafle wektorowe zamiast przesyłania całego pliku do przeglądarki.

## Integralność plików

SHA-256 plików nieskompresowanych:

```text
7a6153e1d87b141f5135effc8ebeee8a1b544e4d6ab69063828d4593c83a3758  budynki-osm-mazowieckie.geojson
63a2d1357b18e6099b9e4ffeaa5a066877311d2a8f92bd9d17cac24ccc76c714  geoazbest-mazowieckie.geojson
```

Pliki przygotowane do GitHub Release:

| Plik | Rozmiar | SHA-256 |
| --- | ---: | --- |
| `budynki-osm-mazowieckie.geojson.gz` | 153 727 306 B (146,61 MiB) | `a7f519fb16748854cbf343d1c136928c773d14fb8dd30d2e884a0bdb003b325b` |
| `geoazbest-mazowieckie.geojson.gz` | 18 690 378 B (17,82 MiB) | `2d66568949bb01e9350dbba988c7e19337c36095c38aca789515b1c9059965d4` |

Weryfikacja po pobraniu:

```bash
shasum -a 256 budynki-osm-mazowieckie.geojson.gz
shasum -a 256 geoazbest-mazowieckie.geojson.gz
gzip -t budynki-osm-mazowieckie.geojson.gz
gzip -t geoazbest-mazowieckie.geojson.gz
```

Rozpakowanie:

```bash
gzip -dk budynki-osm-mazowieckie.geojson.gz
gzip -dk geoazbest-mazowieckie.geojson.gz
```

## Repozytorium i publikacja

Gałąź publikacyjna zawiera wyłącznie ten dokument. Duże lokalne pliki źródłowe i wynikowe nie są dodawane do historii Git, ponieważ przekraczają limit 100 MB zwykłego pliku na GitHubie.

GitHub Release powinien zawierać dwa skompresowane pliki `.geojson.gz`. Nie należy dołączać źródłowej paczki Geofabrik, ponieważ można ją ponownie pobrać z publicznego adresu, a snapshot budynków został już zapisany w pliku wynikowym.
