"""Wycinki dachow lezace na dysku: 801 kadrow z ortofotomapy GUGiK przy 5 cm na piksel.

Autor modelu wyeksportowal dwie cale wsie (Janikow i Bieganow) jako gotowe kadry dachow razem
z metadanymi. Dane leza **poza repozytorium** (70 MB PNG-ow w historii gita byloby pomylka bez
odwrotu), wiec sciezke podaje `VILLAGES_DIR` i na kazdej maszynie jest inna. Struktura jednego
katalogu wsi:

```text
miasteczko1/
  manifest.json      name, buildings_in_boundary, image{size, requested_gsd_m, field_of_view_m}
  metadata.csv       jeden wiersz na zdjecie; `source_id` to nasz `osm_id`, `image_path` to plik
  boundary.geojson   granica wsi z relacji OSM — z niej liczymy obwiednie dla /api/villages
  osm_<osm_id>_<hash>.png
```

**Ten kadr NIE jest naszym kadrem z WMS-a i nie wolno ich mieszac bez powiedzenia, ktory jest ktory.**
Lokalny ma stale **12,8 x 12,8 m** wycentrowane na budynku (256 px przy 5 cm), wiec dach dluzszy niz
13 m jest przyciety; nasz wycinek z WMS-a (`ImageryClient.roof`) liczy kwadrat z marginesem wokol
**calego** budynku, ale za cene 25 cm na piksel i bez znanej daty nalotu. Dlatego kazdy kadr jedzie
do karty budynku razem z opisem zrodla (`roofImage` w `/api/buildings/{osm_id}`) — bez tego podpis
„pokazuje stan z momentu nalotu" staje sie nieprawda dla czesci dachow.

Trzy zasady tego modulu:

* **Indeks czytamy RAZ** (`index_for`, stan na `app.state.local_crops`, wzor z `client_for`
  w `app/imagery.py`). 801 wierszy CSV na kazde zapytanie o miniature to 25 odczytow na jedno
  otwarcie panelu z siatka miniatur.
* **Brak konfiguracji nie jest bledem.** Puste `VILLAGES_DIR`, nieistniejacy katalog, katalog bez
  `metadata.csv`, uszkodzony CSV, brakujacy albo nieczytelny PNG — kazdy z tych przypadkow konczy
  sie pustym (albo krotszym) indeksem, czyli cichym powrotem do WMS-a. Aplikacja bez tych danych ma
  dzialac dokladnie jak dotad, wiec zaden blad danych nie ma prawa doleciec do odpowiedzi HTTP.
* **Sciezki z CSV nie moga wyjsc z katalogu wsi.** `image_path` przychodzi z pliku, ktorego nie
  kontrolujemy, a endpoint oddaje jego bajty uzytkownikowi — to jedyne miejsce w tej funkcji, gdzie
  wejsciem jest plik z dysku. Pilnuje tego `safe_path`.
"""

import csv
import json
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.imagery import PNG_MAGIC

MANIFEST_NAME = "manifest.json"
METADATA_NAME = "metadata.csv"
BOUNDARY_NAME = "boundary.geojson"

# Kolumny `metadata.csv`, ktore nas dotycza. `source_id` to nasz `osm_id` (sprawdzone: wszystkie
# 801 identyfikatorow istnieje w naszym PostGIS) — dopasowanie idzie po nim, nie geometrycznie.
ID_COLUMN = "source_id"
PATH_COLUMN = "image_path"
GSD_COLUMN = "native_gsd_m"
DATE_COLUMN = "ortho_acquisition_date"

# Obwiednia granicy jedzie do `fitBounds`, wiec cztery miejsca po kropce (~11 m na 51. paraleli)
# sa dokladnosciowo bez znaczenia, a odpowiedz zostaje czytelna dla czlowieka.
BOUNDS_DECIMALS = 4

# Kadr wsi wazy 60-100 KB. Limit jest po to, zeby `image_path` wskazujacy na cos duzego (plik przyszedl
# z zewnatrz, wiec nie jest obietnica) nie wciagnal do pamieci procesu kilkuset megabajtow.
MAX_CROP_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class RoofCrop:
    """Jeden kadr z dysku: sciezka plus to, co o nim naprawde wiemy.

    `gsd_m`, `frame_m` i `acquired_on` moga byc `None`, gdy metadane ich nie podaja — wtedy karta
    budynku napisze o tym kadrze tylko tyle, ile wiadomo, zamiast dopisac liczbe z sufitu.
    """

    osm_id: int
    path: Path
    village: str
    gsd_m: float | None = None
    frame_m: float | None = None
    acquired_on: str | None = None


@dataclass(frozen=True)
class Village:
    """Wies opisana tak, jak wystawia ja `/api/villages`.

    `crops` to liczba wierszy w `metadata.csv`, a nie liczba plikow, ktore udalo sie zindeksowac —
    tak jest w kontrakcie i tak jest uczciwie wobec eksportu: wiersz istnieje takze wtedy, gdy PNG
    zniknal po drodze. Rozjazd tych dwoch liczb widac po tym, ze dachy bez pliku wracaja do WMS-a.
    """

    folder: str
    name: str
    sw: tuple[float, float]
    ne: tuple[float, float]
    crops: int
    buildings: int
    gsd_m: float | None = None
    frame_m: float | None = None
    acquired_from: str | None = None
    acquired_to: str | None = None


@dataclass(frozen=True)
class CropIndex:
    """Caly eksport wczytany raz: wsie do spisu i kadry pod `osm_id`."""

    villages: tuple[Village, ...] = ()
    crops: dict[int, RoofCrop] = field(default_factory=dict)

    def find(self, osm_id: int) -> RoofCrop | None:
        """Kadr tego budynku albo None, czyli „pytaj WMS-a jak dotad"."""
        return self.crops.get(osm_id)

    def __len__(self) -> int:
        return len(self.crops)


# Indeks pustego swiata: zadnej wsi, zadnego kadru. Oddajemy go przy kazdym rodzaju braku danych,
# bo wtedy cala funkcja po prostu nie istnieje i nic o niej nie trzeba wiedziec wyzej.
EMPTY = CropIndex()


def whole_number(raw: Any) -> int | None:
    """Liczba calkowita >= 0 albo None. CSV i JSON podaja liczby napisami, wiec int() nie wystarczy."""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def positive_int(raw: Any) -> int | None:
    value = whole_number(raw)
    return value if value is not None and value > 0 else None


def positive_float(raw: Any) -> float | None:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0.0 else None


def iso_date(raw: Any) -> str | None:
    """Data nalotu w formacie ISO albo None.

    Przepuszczamy ja przez `date.fromisoformat`, bo ta wartosc trafia do karty budynku jako data
    nalotu i do min/max w `/api/villages` — cokolwiek innego niz data nie moze tam dojechac.
    """
    try:
        return date.fromisoformat(str(raw).strip()).isoformat()
    except (TypeError, ValueError):
        return None


def single_value(values: Sequence[float]) -> float | None:
    """Jedna wartosc, gdy wszystkie wiersze podaja te sama; inaczej None.

    Rozdzielczosc rodzima jest cecha eksportu, nie pojedynczego wiersza, wiec w spisie wsi ma sens
    tylko wtedy, gdy jest jedna. Przy wielu roznych wartosciach mowimy „nie wiemy" zamiast wybierac
    jedna z nich za autora danych — pojedyncze kadry i tak niosa swoja wlasna liczbe.
    """
    unique = set(values)
    return unique.pop() if len(unique) == 1 else None


def safe_path(folder: Path, raw: Any) -> Path | None:
    """Sciezka do pliku kadru albo None, gdy wychodzi poza katalog wsi.

    `image_path` przychodzi z pliku, ktorego nie kontrolujemy, a `/api/buildings/{osm_id}/roof.png`
    oddaje bajty tego pliku uzytkownikowi. Dlatego odrzucamy wszystko, co po zlaczeniu i normalizacji
    (`resolve` rozwija tez `..` i linki symboliczne) nie lezy wewnatrz katalogu wsi, a sciezke
    bezwzgledna odrzucamy od razu: `Path("/wies") / "/etc/passwd"` w ogole nie sklada, tylko oddaje
    drugi argument, wiec sam `is_relative_to` byl by tu sprawdzeniem po fakcie.
    """
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute() or candidate.drive or candidate.root:
        return None
    try:
        base = folder.resolve(strict=False)
        target = (base / candidate).resolve(strict=False)
    except OSError:
        return None
    if target == base or not target.is_relative_to(base):
        return None
    return target


def points_in(node: Any) -> Iterator[tuple[float, float]]:
    """Wszystkie pary wspolrzednych z zagniezdzonych list GeoJSON-a (Polygon, MultiPolygon, ...)."""
    if not isinstance(node, list | tuple):
        return
    head = node[:2]
    if len(head) == 2 and all(isinstance(value, int | float) and not isinstance(value, bool) for value in head):
        yield float(head[0]), float(head[1])
        return
    for item in node:
        yield from points_in(item)


def bounds_of(geojson: Any) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Obwiednia granicy wsi jako (sw, ne) w stopniach, albo None gdy granicy nie da sie odczytac.

    Przyjmujemy `Feature` (tak wyglada `boundary.geojson`) albo sama geometrie. Punkty poza zakresem
    ukladu WGS84 pomijamy — jeden zepsuty wierzcholek rozciagnalby obwiednie na pol swiata.
    """
    node = geojson.get("geometry", geojson) if isinstance(geojson, dict) else geojson
    coordinates = node.get("coordinates") if isinstance(node, dict) else None
    points = [(lng, lat) for lng, lat in points_in(coordinates) if abs(lng) <= 180.0 and abs(lat) <= 90.0]
    if not points:
        return None
    lngs = [lng for lng, _ in points]
    lats = [lat for _, lat in points]
    sw = (round(min(lngs), BOUNDS_DECIMALS), round(min(lats), BOUNDS_DECIMALS))
    ne = (round(max(lngs), BOUNDS_DECIMALS), round(max(lats), BOUNDS_DECIMALS))
    return sw, ne


def frame_from(image: Any) -> float | None:
    """Bok kadru w metrach z `image.field_of_view_m` w manifescie.

    Manifest podaje pare `[12.8, 12.8]`, bo kadr jest kwadratowy. Gdyby boki byly rozne, jedna
    liczba nie opisywalaby tego kadru — wtedy oddajemy None, bo lepiej nie podac nic niz podac
    polowe prawdy o wielkosci tego, co widac na zdjeciu.
    """
    value = image.get("field_of_view_m") if isinstance(image, dict) else None
    if isinstance(value, list | tuple):
        sides = [positive_float(side) for side in value]
        if not sides or None in sides or len(set(sides)) != 1:
            return None
        return sides[0]
    return positive_float(value)


def read_json(path: Path) -> Any | None:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):  # brak pliku, zly kodowanie (UnicodeDecodeError to ValueError), zly JSON
        return None


def read_rows(path: Path) -> list[dict[str, str]] | None:
    """Wiersze `metadata.csv` albo None, gdy tych metadanych nie da sie uzyc.

    None znaczy „ta wies nie istnieje dla nas": brak pliku, zle kodowanie, plik, ktory nie jest CSV,
    albo naglowek bez `source_id`/`image_path`. Wtedy nie ma ani kadrow, ani czego opisywac
    w `/api/villages`, a `roof.png` dziala jak dotad, czyli przez WMS.
    """
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            names = reader.fieldnames
            if names is None or ID_COLUMN not in names or PATH_COLUMN not in names:
                return None
            return list(reader)
    except (OSError, ValueError, csv.Error):
        return None


def crop_from(folder: Path, row: dict[str, str], frame_m: float | None) -> RoofCrop | None:
    """Kadr z jednego wiersza CSV albo None, gdy tego wiersza nie da sie uzyc.

    Sprawdzamy istnienie pliku i jego rozmiar tutaj, przy wczytywaniu indeksu, a nie przy zadaniu:
    dzieki temu `roofImage` w karcie budynku mowi o kadrze, ktory naprawde lezy na dysku. Plik, ktory
    zniknie po wczytaniu indeksu, jest wylapany drugi raz w `read_crop` — wtedy odpowiedz wraca do
    WMS-a, wiec zdjecie jest, choc karta obiecywala inne zrodlo.
    """
    osm_id = positive_int(row.get(ID_COLUMN))
    path = safe_path(folder, row.get(PATH_COLUMN))
    if osm_id is None or path is None:
        return None
    try:
        if not path.is_file() or path.stat().st_size > MAX_CROP_BYTES:
            return None
    except OSError:
        return None
    return RoofCrop(
        osm_id=osm_id,
        path=path,
        village=folder.name,
        gsd_m=positive_float(row.get(GSD_COLUMN)),
        frame_m=frame_m,
        acquired_on=iso_date(row.get(DATE_COLUMN)),
    )


def describe(folder: Path, manifest: Any, crops: list[RoofCrop], rows: int) -> Village | None:
    """Opis wsi do `/api/villages` albo None, gdy nie da sie go podac uczciwie.

    Wymagamy nazwy, liczby budynkow w granicy i obwiedni granicy, bo bez ktorejkolwiek z nich wpis
    w spisie nie mialby na co pokazac na mapie ani czego nazwac. Kadry z takiej wsi i tak dzialaja —
    spis jest po to, zeby po nich skakac, a nie po to, zeby warunkowac ich istnienie.
    """
    name = manifest.get("name") if isinstance(manifest, dict) else None
    buildings = whole_number(manifest.get("buildings_in_boundary")) if isinstance(manifest, dict) else None
    bounds = bounds_of(read_json(folder / BOUNDARY_NAME))
    if not isinstance(name, str) or not name.strip() or buildings is None or bounds is None:
        return None
    dates = sorted(crop.acquired_on for crop in crops if crop.acquired_on is not None)
    return Village(
        folder=folder.name,
        name=name.strip(),
        sw=bounds[0],
        ne=bounds[1],
        crops=rows,
        buildings=buildings,
        gsd_m=single_value([crop.gsd_m for crop in crops if crop.gsd_m is not None]),
        frame_m=single_value([crop.frame_m for crop in crops if crop.frame_m is not None]),
        acquired_from=dates[0] if dates else None,
        acquired_to=dates[-1] if dates else None,
    )


def load_village(folder: Path) -> tuple[Village | None, list[RoofCrop]]:
    """Jedna wies: kadry pod `osm_id` i (jesli da sie opisac) wpis do spisu."""
    rows = read_rows(folder / METADATA_NAME)
    if rows is None:
        return None, []
    manifest = read_json(folder / MANIFEST_NAME)
    frame_m = frame_from(manifest.get("image") if isinstance(manifest, dict) else None)
    crops = [crop for crop in (crop_from(folder, row, frame_m) for row in rows) if crop is not None]
    return describe(folder, manifest, crops, len(rows)), crops


def load_index(root: str | os.PathLike[str] | None) -> CropIndex:
    """Caly katalog eksportu wczytany raz. Kazdy blad danych konczy sie krotszym indeksem, nie wyjatkiem.

    Puste `root` (domyslne `VILLAGES_DIR`) znaczy „nie mamy tych danych" i jest zwyczajna sytuacja:
    aplikacja dziala wtedy dokladnie jak dotad, a `/api/villages` oddaje pusta liste.

    Zmierzone na prawdziwym eksporcie (801 wierszy, dwie wsie): **0,28 s**, z czego wiekszosc to
    `resolve` i `stat` na kazdym pliku. To jest cena placona raz na proces, przez pierwsze zadanie,
    ktore pyta o kadr — i dlatego indeks nie moze byc wczytywany przy kazdym zapytaniu.
    """
    if not root:
        return EMPTY
    try:
        base = Path(root).expanduser()
        folders = sorted(entry for entry in base.iterdir() if entry.is_dir())
    except (OSError, ValueError, RuntimeError):
        # Nieistniejacy katalog, brak uprawnien, sciezka wskazujaca na plik, sciezka z bajtem zerowym,
        # `~` bez katalogu domowego. Zla konfiguracja nie moze wywalic startu ani odpowiedzi.
        return EMPTY

    villages: list[Village] = []
    crops: dict[int, RoofCrop] = {}
    for folder in folders:
        try:
            village, found = load_village(folder)
        except Exception:  # katalog wsi moze byc uszkodzony na sposob, ktorego nie przewidzielismy
            continue
        for crop in found:
            # Ten sam budynek w dwoch wsiach to niespojnosc eksportu, nie nasza decyzja — bierzemy
            # pierwszy kadr i nie udajemy, ze umiemy wybrac lepszy.
            crops.setdefault(crop.osm_id, crop)
        if village is not None:
            villages.append(village)
    return CropIndex(tuple(villages), crops)


def read_crop(crop: RoofCrop) -> bytes | None:
    """Bajty kadru albo None, gdy pliku nie da sie podac.

    Sprawdzamy magiczne bajty PNG, bo `Content-Type: image/png` nad czymkolwiek innym jest klamstwem
    wobec przegladarki — i to ta sama ostroznosc, ktora `looks_like_png` stosuje do odpowiedzi WMS-a.
    None znaczy „wroc do WMS-a": brak zdjecia z powodu naszego pliku nie moze zabrac uzytkownikowi
    zdjecia, ktore da sie jeszcze pobrac.
    """
    try:
        payload = crop.path.read_bytes()
    except OSError:
        return None
    if len(payload) > MAX_CROP_BYTES or not payload.startswith(PNG_MAGIC):
        return None
    return payload


def index_for(app: Any) -> CropIndex:
    """Indeks trzymany na `app.state`, wczytany przy pierwszym zadaniu, ktore go potrzebuje.

    Miedzy sprawdzeniem i zapisem nie ma `await`, wiec w jednowatkowej petli nie ma tu wyscigu —
    ten sam wzor co `client_for` w `app/imagery.py` i `get_provider` w `app/prediction.py`. Test
    moze podstawic wlasny indeks, ustawiajac `app.state.local_crops` przed zapytaniem.
    """
    index: CropIndex | None = getattr(app.state, "local_crops", None)
    if index is None:
        index = load_index(app.state.settings.villages_dir)
        app.state.local_crops = index
    return index
