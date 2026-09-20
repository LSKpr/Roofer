"""Wycinki dachow z dysku: atrapa wsi w `tmp_path`, transport httpx podstawiony, baza to FakePool.

Bez sieci i bez prawdziwego eksportu (ten lezy poza repozytorium i wazy 70 MB). Najwazniejszy test
w tym pliku to ten, ktory sprawdza, ze przy pliku na dysku **ani jedno zapytanie HTTP nie wychodzi** —
reszta pilnuje, zeby kazdy rodzaj uszkodzenia danych konczyl sie cichym powrotem do WMS-a, a nie
wyjatkiem w odpowiedzi.
"""

import csv
import json
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import localcrops
from app.config import Settings
from app.imagery import PNG_MAGIC, ImageryClient
from app.localcrops import (
    EMPTY,
    CropIndex,
    RoofCrop,
    bounds_of,
    frame_from,
    index_for,
    load_index,
    read_crop,
    safe_path,
    single_value,
)
from app.main import create_app
from app.routes.buildings import WMS_ROOF_IMAGE, roof_image_of
from tests.conftest import FakePool

# Prawdziwe `osm_id` z eksportu (Janikow): pliki nazywaja sie `osm_<osm_id>_<hash>.png`, a `source_id`
# w metadata.csv to dokladnie ten numer. Trzeci identyfikator jest spoza eksportu — to budynek, ktory
# ma wracac do WMS-a.
LOCAL_ID = 167245645
SECOND_LOCAL_ID = 167245647
REMOTE_ID = 27469148

# Kolumny prawdziwego metadata.csv, w tej samej kolejnosci. Reszty kolumn eksportu (miary jakosci,
# poligon dachu w pikselach) nie ma, bo indeks ich nie czyta — a test, ktory je przepisuje, klamie
# o tym, co jest wymagane.
COLUMNS = (
    "building_id",
    "source_id",
    "building_type",
    "longitude",
    "latitude",
    "ortho_sheet",
    "ortho_year",
    "ortho_acquisition_date",
    "native_gsd_m",
    "width",
    "height",
    "quality_status",
    "image_path",
    "image_sha256",
    "image_bytes",
)

# Granica Janikowa w prawdziwym boundary.geojson ma obwiednie 21,5703279 / 51,5574905 do
# 21,6084446 / 51,5801923 — atrapa uzywa tych samych liczb, zeby test pokazywal zaokraglenie
# do czterech miejsc, ktore wystawia kontrakt.
BOUNDARY_POINTS = [
    [21.5703279, 51.5574905],
    [21.6084446, 51.5574905],
    [21.6084446, 51.5801923],
    [21.5703279, 51.5801923],
    [21.5703279, 51.5574905],
]
SW = {"lng": 21.5703, "lat": 51.5575}
NE = {"lng": 21.6084, "lat": 51.5802}

LOCAL_PNG = PNG_MAGIC + b"kadr z dysku"
WMS_PNG = PNG_MAGIC + b"kadr z WMS-a"

ROOF_PATH = "/api/buildings/{osm_id}/roof.png"
BUILDING_PATH = "/api/buildings/{osm_id}"
VILLAGES_PATH = "/api/villages"

# Kolejnosc kolumn BUILDING_SQL: id, fclass, osm_type, name, area_m2, lng, lat, registry_matches,
# records, other_intersecting. FakePool nie ma `cursor.description`, wiec nazwy podajemy tutaj.
BUILDING_COLUMNS = (
    "id",
    "fclass",
    "osm_type",
    "name",
    "area_m2",
    "lng",
    "lat",
    "registry_matches",
    "records",
    "other_intersecting",
)
BUILDING_ROW = (LOCAL_ID, "building", "house", None, 126.6, 21.5891, 51.5718, 0, [], 0)


class Column:
    """Atrapa `cursor.description` psycopg: `read_building` czyta z niej nazwy kolumn."""

    def __init__(self, name: str) -> None:
        self.name = name


class NamedCursor:
    def __init__(self, row: tuple[Any, ...] | None, names: Sequence[str]) -> None:
        self.row = row
        self.description = [Column(name) for name in names]

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


class NamedPool(FakePool):
    """FakePool, ktory umie oddac wiersz z nazwami kolumn — tyle potrzebuje `/api/buildings/{id}`."""

    def __init__(self, row: tuple[Any, ...] | None, names: Sequence[str] = BUILDING_COLUMNS) -> None:
        super().__init__(row=row)
        self.names = names

    async def _execute(self, _sql: str, _params: Any = None) -> NamedCursor:
        return NamedCursor(self.row, self.names)

    def connection(self, timeout: float | None = None) -> Any:  # type: ignore[override]
        pool = self

        class Connection:
            async def execute(self, sql: str, params: Any = None) -> NamedCursor:
                return await pool._execute(sql, params)

        class Context:
            async def __aenter__(self) -> Connection:
                pool.timeouts.append(timeout)
                return Connection()

            async def __aexit__(self, *_exc: Any) -> None:
                return None

        return Context()


def csv_row(osm_id: int, image_path: str, acquired_on: str = "2023-12-05", gsd: str = "0.05") -> dict[str, str]:
    return {
        "building_id": "35982",
        "source_id": str(osm_id),
        "building_type": "house",
        "longitude": "21.589152540173213",
        "latitude": "51.571854520149316",
        "ortho_sheet": "M-34-20-A-c-2-1",
        "ortho_year": "2023",
        "ortho_acquisition_date": acquired_on,
        "native_gsd_m": gsd,
        "width": "256",
        "height": "256",
        "quality_status": "accepted",
        "image_path": image_path,
        "image_sha256": "5896df9f21e963c4",
        "image_bytes": str(len(LOCAL_PNG)),
    }


def write_village(
    root: Path,
    folder: str = "miasteczko1",
    name: str = "Janikow",
    rows: Iterable[dict[str, str]] | None = None,
    files: Iterable[str] | None = None,
    buildings: int = 458,
    boundary: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    metadata: str | None = None,
) -> Path:
    """Atrapa katalogu wsi: PNG-i, metadata.csv, manifest.json i boundary.geojson.

    Kazdy element mozna wylaczyc (`None` w gotowym pliku) albo podmienic na uszkodzony — po to jest
    ten builder, zeby test uszkodzenia dotykal jednego pliku i bylo widac ktorego.
    """
    village = root / folder
    village.mkdir(parents=True, exist_ok=True)
    rows = list(rows) if rows is not None else [csv_row(LOCAL_ID, f"osm_{LOCAL_ID}_5896df9f21e963c4.png")]
    names = files if files is not None else [row["image_path"] for row in rows]
    for file_name in names:
        (village / file_name).write_bytes(LOCAL_PNG)

    if metadata is not None:
        (village / "metadata.csv").write_text(metadata, encoding="utf-8")
    else:
        with (village / "metadata.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(COLUMNS))
            writer.writeheader()
            writer.writerows(rows)

    payload = (
        manifest
        if manifest is not None
        else {
            "folder": folder,
            "name": name,
            "osm_relation_id": 3201819,
            "buildings_in_boundary": buildings,
            "images_saved": len(rows),
            "image": {"size": [256, 256], "requested_gsd_m": 0.05, "field_of_view_m": [12.8, 12.8]},
        }
    )
    (village / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    (village / "boundary.geojson").write_text(
        json.dumps(boundary if boundary is not None else feature(BOUNDARY_POINTS)), encoding="utf-8"
    )
    return village


def feature(points: list[list[float]]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"name": "Janikow"},
        "geometry": {"type": "Polygon", "coordinates": [points]},
    }


def wms_response(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "image/png"}, content=WMS_PNG)


def recording_handler() -> tuple[list[httpx.Request], Callable[[httpx.Request], httpx.Response]]:
    """Atrapa transportu, ktora pamieta kazde zapytanie — wzor z tests/test_imagery.py."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return wms_response(request)

    return seen, handler


def app_with(
    villages_dir: str = "",
    pool: FakePool | None = None,
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> FastAPI:
    """Aplikacja z podstawionym transportem do WMS-a i podana sciezka do eksportu.

    `villages_dir` podajemy jawnie zawsze, bo `Settings` czyta `../.env` — bez tego test o „pustej
    konfiguracji" zaczalby zalezec od tego, czy na maszynie ustawiono VILLAGES_DIR.
    """
    settings = Settings(database_url="postgresql://unused", villages_dir=villages_dir)
    app = create_app(settings, pool_factory=lambda _settings: pool or FakePool())
    app.state.imagery = ImageryClient(
        base_url="https://wms.test/orto",
        layer="Raster",
        transport=httpx.MockTransport(handler or wms_response),
    )
    return app


# --- indeks ------------------------------------------------------------------------------------


def test_the_index_finds_a_crop_by_osm_id(tmp_path: Path) -> None:
    write_village(tmp_path)

    index = load_index(tmp_path)
    crop = index.find(LOCAL_ID)

    assert crop is not None
    assert crop.path.name == f"osm_{LOCAL_ID}_5896df9f21e963c4.png"
    assert (crop.gsd_m, crop.frame_m, crop.acquired_on) == (0.05, 12.8, "2023-12-05")
    assert crop.village == "miasteczko1"
    assert index.find(REMOTE_ID) is None
    assert len(index) == 1


def test_an_empty_setting_means_the_feature_is_off(tmp_path: Path) -> None:
    """Puste VILLAGES_DIR nie jest bledem: aplikacja ma dzialac dokladnie jak przed ta zmiana."""
    write_village(tmp_path)

    assert load_index("") is EMPTY
    assert load_index(None) is EMPTY
    assert load_index("").villages == ()


def test_a_missing_directory_gives_an_empty_index(tmp_path: Path) -> None:
    assert load_index(tmp_path / "nie-ma-takiego-katalogu") == EMPTY


@pytest.mark.parametrize("root", ["metadata.csv", "sciezka\x00z-zerem", "~nie-ma-takiego-uzytkownika/wsie"])
def test_a_nonsense_setting_gives_an_empty_index(tmp_path: Path, root: str) -> None:
    """Zla wartosc VILLAGES_DIR nie moze wywalic odpowiedzi — najwyzej wylacza funkcje."""
    write_village(tmp_path)
    candidate = str(tmp_path / "miasteczko1" / root) if root == "metadata.csv" else root

    assert load_index(candidate) == EMPTY


def test_a_directory_without_metadata_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "miasteczko1").mkdir()
    (tmp_path / "miasteczko1" / "osm_1_a.png").write_bytes(LOCAL_PNG)

    index = load_index(tmp_path)

    assert len(index) == 0
    assert index.villages == ()


@pytest.mark.parametrize(
    "metadata",
    [
        "to nie jest CSV",
        "source_id,image_path\n",  # naglowek bez wierszy
        "kolumna_a,kolumna_b\n1,2\n",  # CSV bez naszych kolumn
        "source_id,image_path\nbez-liczby,osm_1_a.png\n",
        "\x00\x01\x02binarne smieci\x00",
    ],
)
def test_a_broken_csv_does_not_raise(tmp_path: Path, metadata: str) -> None:
    write_village(tmp_path, metadata=metadata)

    index = load_index(tmp_path)

    assert len(index) == 0
    assert index.find(LOCAL_ID) is None


def test_a_broken_manifest_leaves_the_crops_working(tmp_path: Path) -> None:
    """Uszkodzony manifest zabiera wies ze spisu, ale nie zabiera zdjec, ktore leza na dysku."""
    write_village(tmp_path, manifest={"name": "", "buildings_in_boundary": "?"})

    index = load_index(tmp_path)

    assert index.villages == ()
    assert index.find(LOCAL_ID) is not None
    assert index.find(LOCAL_ID).frame_m is None  # type: ignore[union-attr]


def test_a_missing_png_listed_in_the_csv_breaks_neither_the_index_nor_the_list(tmp_path: Path) -> None:
    rows = [
        csv_row(LOCAL_ID, f"osm_{LOCAL_ID}_a.png"),
        csv_row(SECOND_LOCAL_ID, f"osm_{SECOND_LOCAL_ID}_b.png"),
    ]
    write_village(tmp_path, rows=rows, files=[f"osm_{LOCAL_ID}_a.png"])  # drugiego pliku nie ma

    index = load_index(tmp_path)

    assert index.find(LOCAL_ID) is not None
    assert index.find(SECOND_LOCAL_ID) is None  # ten dach wroci do WMS-a
    assert index.villages[0].crops == 2  # `crops` to wiersze metadanych, nie pliki na dysku


def test_a_crop_bigger_than_the_budget_is_not_indexed(tmp_path: Path) -> None:
    write_village(tmp_path)
    (tmp_path / "miasteczko1" / f"osm_{LOCAL_ID}_5896df9f21e963c4.png").write_bytes(
        PNG_MAGIC + b"x" * localcrops.MAX_CROP_BYTES
    )

    assert load_index(tmp_path).find(LOCAL_ID) is None


def test_two_villages_are_read_into_one_index(tmp_path: Path) -> None:
    write_village(tmp_path)
    write_village(
        tmp_path,
        folder="miasteczko2",
        name="Bieganow",
        buildings=549,
        rows=[csv_row(SECOND_LOCAL_ID, f"osm_{SECOND_LOCAL_ID}_b.png", acquired_on="2023-12-12")],
    )

    index = load_index(tmp_path)

    assert [village.folder for village in index.villages] == ["miasteczko1", "miasteczko2"]
    assert len(index) == 2


# --- sciezki z pliku, ktorego nie kontrolujemy --------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "../../etc/passwd",
        "..\\..\\Windows\\win.ini",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "C:/Windows/win.ini",
        "podkatalog/../../poza/wsia.png",
        "",
        "   ",
    ],
)
def test_a_path_leaving_the_village_directory_is_rejected(tmp_path: Path, raw: str) -> None:
    """`image_path` przychodzi z pliku, ktorego nie kontrolujemy, a endpoint oddaje jego bajty."""
    assert safe_path(tmp_path, raw) is None


def test_a_path_inside_the_village_directory_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "osm_1_a.png").write_bytes(LOCAL_PNG)

    assert safe_path(tmp_path, "osm_1_a.png") == (tmp_path / "osm_1_a.png").resolve()
    assert safe_path(tmp_path, "podkatalog/osm_1_a.png") == (tmp_path / "podkatalog" / "osm_1_a.png").resolve()


def test_an_escaping_row_is_dropped_from_the_index(tmp_path: Path) -> None:
    secret = tmp_path / "sekret.png"
    secret.write_bytes(LOCAL_PNG)
    rows = [
        csv_row(LOCAL_ID, "../sekret.png"),
        csv_row(SECOND_LOCAL_ID, str(secret)),
    ]
    write_village(tmp_path, rows=rows, files=[])

    index = load_index(tmp_path)

    assert len(index) == 0
    assert index.villages[0].crops == 2  # wiersze byly, kadrow z nich nie ma


# --- male jednostki ----------------------------------------------------------------------------


def test_bounds_come_from_the_boundary_geometry() -> None:
    assert bounds_of(feature(BOUNDARY_POINTS)) == ((SW["lng"], SW["lat"]), (NE["lng"], NE["lat"]))


def test_bounds_read_a_multipolygon_and_a_bare_geometry() -> None:
    multi = {"type": "MultiPolygon", "coordinates": [[BOUNDARY_POINTS], [[[21.6, 51.6], [21.7, 51.7]]]]}

    assert bounds_of(multi) == ((SW["lng"], SW["lat"]), (21.7, 51.7))
    assert bounds_of({"type": "Polygon", "coordinates": [BOUNDARY_POINTS]}) is not None


@pytest.mark.parametrize(
    "geojson",
    [None, {}, {"type": "Feature"}, {"geometry": {"coordinates": []}}, {"geometry": {"coordinates": "nie lista"}}],
)
def test_bounds_of_nonsense_are_unknown(geojson: Any) -> None:
    assert bounds_of(geojson) is None


def test_a_single_broken_vertex_does_not_stretch_the_bounds() -> None:
    points = [*BOUNDARY_POINTS, [999.0, 999.0]]

    assert bounds_of(feature(points)) == ((SW["lng"], SW["lat"]), (NE["lng"], NE["lat"]))


def test_the_frame_is_read_from_the_manifest_pair() -> None:
    assert frame_from({"field_of_view_m": [12.8, 12.8]}) == 12.8
    assert frame_from({"field_of_view_m": 12.8}) == 12.8
    # Kadr niekwadratowy nie da sie opisac jedna liczba, wiec wolimy nie podac zadnej.
    assert frame_from({"field_of_view_m": [12.8, 25.6]}) is None
    assert frame_from({"field_of_view_m": []}) is None
    assert frame_from({}) is None
    assert frame_from(None) is None


def test_one_value_is_a_value_and_many_are_unknown() -> None:
    assert single_value([0.05, 0.05]) == 0.05
    assert single_value([0.05, 0.25]) is None
    assert single_value([]) is None


def test_read_crop_refuses_a_file_that_is_not_a_png(tmp_path: Path) -> None:
    path = tmp_path / "nie-png.png"
    path.write_bytes(b"<html>przepraszamy</html>")
    crop = RoofCrop(osm_id=LOCAL_ID, path=path, village="miasteczko1")

    assert read_crop(crop) is None
    assert read_crop(RoofCrop(osm_id=LOCAL_ID, path=tmp_path / "nie-ma.png", village="x")) is None


# --- wybor zrodla w /api/buildings/{osm_id}/roof.png -------------------------------------------


def test_a_local_file_beats_the_wms_and_no_request_leaves_the_process(tmp_path: Path) -> None:
    """Sedno tego zadania: mamy kadr na dysku, wiec do GUGiK nie idzie ani jedno zapytanie."""
    write_village(tmp_path)
    seen, handler = recording_handler()
    pool = FakePool(row=(1000.0, 2000.0, 1020.0, 2010.0))

    with TestClient(app_with(str(tmp_path), pool=pool, handler=handler)) as client:
        response = client.get(ROOF_PATH.format(osm_id=LOCAL_ID))

    assert response.status_code == 200
    assert response.content == LOCAL_PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert seen == []


def test_a_building_without_a_local_crop_goes_to_the_wms(tmp_path: Path) -> None:
    write_village(tmp_path)
    seen, handler = recording_handler()
    pool = FakePool(row=(1000.0, 2000.0, 1020.0, 2010.0))

    with TestClient(app_with(str(tmp_path), pool=pool, handler=handler)) as client:
        response = client.get(ROOF_PATH.format(osm_id=REMOTE_ID))

    assert response.status_code == 200
    assert response.content == WMS_PNG
    assert len(seen) == 1


def test_without_configuration_even_a_building_from_the_export_goes_to_the_wms(tmp_path: Path) -> None:
    write_village(tmp_path)
    seen, handler = recording_handler()
    pool = FakePool(row=(1000.0, 2000.0, 1020.0, 2010.0))

    with TestClient(app_with("", pool=pool, handler=handler)) as client:
        response = client.get(ROOF_PATH.format(osm_id=LOCAL_ID))

    assert response.content == WMS_PNG
    assert len(seen) == 1


def test_a_file_that_disappears_after_indexing_falls_back_to_the_wms(tmp_path: Path) -> None:
    village = write_village(tmp_path)
    seen, handler = recording_handler()
    pool = FakePool(row=(1000.0, 2000.0, 1020.0, 2010.0))
    app = app_with(str(tmp_path), pool=pool, handler=handler)

    with TestClient(app) as client:
        index_for(app)  # wczytuje indeks, dopoki plik jeszcze istnieje
        (village / f"osm_{LOCAL_ID}_5896df9f21e963c4.png").unlink()
        response = client.get(ROOF_PATH.format(osm_id=LOCAL_ID))

    assert response.status_code == 200
    assert response.content == WMS_PNG
    assert len(seen) == 1


def test_a_broken_directory_does_not_break_the_endpoint(tmp_path: Path) -> None:
    write_village(tmp_path, metadata="to nie jest CSV")
    seen, handler = recording_handler()
    pool = FakePool(row=(1000.0, 2000.0, 1020.0, 2010.0))

    with TestClient(app_with(str(tmp_path), pool=pool, handler=handler)) as client:
        response = client.get(ROOF_PATH.format(osm_id=LOCAL_ID))

    assert response.status_code == 200
    assert response.content == WMS_PNG
    assert len(seen) == 1


@pytest.mark.parametrize("size", [128, 384, 1024])
def test_size_is_ignored_for_a_local_file(tmp_path: Path, size: int) -> None:
    """Plik z eksportu ma 256 x 256 i nie mamy czym go przeskalowac, wiec `size` dotyczy tylko WMS-a."""
    write_village(tmp_path)
    seen, handler = recording_handler()

    with TestClient(app_with(str(tmp_path), handler=handler)) as client:
        response = client.get(ROOF_PATH.format(osm_id=LOCAL_ID), params={"size": size})

    assert response.status_code == 200
    assert response.content == LOCAL_PNG
    assert seen == []


def test_a_size_outside_the_range_is_still_rejected(tmp_path: Path) -> None:
    """Walidacja parametru nie zmienila sie razem ze zrodlem kadru."""
    write_village(tmp_path)

    with TestClient(app_with(str(tmp_path))) as client:
        response = client.get(ROOF_PATH.format(osm_id=LOCAL_ID), params={"size": 2048})

    assert response.status_code == 422


def test_a_local_crop_needs_no_database_at_all(tmp_path: Path) -> None:
    """Siatka miniatur otwiera 25 takich zadan naraz — kadr z dysku nie ma po co pytac o obwiednie."""
    write_village(tmp_path)
    pool = FakePool(error=OSError("connection refused"))

    with TestClient(app_with(str(tmp_path), pool=pool)) as client:
        response = client.get(ROOF_PATH.format(osm_id=LOCAL_ID))

    assert response.status_code == 200
    assert response.content == LOCAL_PNG
    assert pool.timeouts == []


def test_the_index_is_read_once_not_per_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """801 wierszy CSV na kazda miniature to 25 odczytow na jedno otwarcie panelu."""
    write_village(tmp_path)
    calls: list[Any] = []
    real = localcrops.load_index

    def counting(root: Any) -> CropIndex:
        calls.append(root)
        return real(root)

    monkeypatch.setattr(localcrops, "load_index", counting)

    with TestClient(app_with(str(tmp_path))) as client:
        client.get(ROOF_PATH.format(osm_id=LOCAL_ID))
        client.get(ROOF_PATH.format(osm_id=LOCAL_ID))
        client.get(VILLAGES_PATH)

    assert len(calls) == 1


# --- roofImage w /api/buildings/{osm_id} -------------------------------------------------------


def test_roof_image_of_a_local_crop_says_what_the_frame_really_is() -> None:
    crop = RoofCrop(osm_id=LOCAL_ID, path=Path("x.png"), village="miasteczko1", gsd_m=0.05, frame_m=12.8)

    assert roof_image_of(crop).source == "local"
    assert roof_image_of(crop).frame_m == 12.8
    assert roof_image_of(None) == WMS_ROOF_IMAGE
    # Przy WMS-ie nie znamy ani daty nalotu, ani rodzimej rozdzielczosci kadru — i tak to mowimy.
    assert (WMS_ROOF_IMAGE.gsd_m, WMS_ROOF_IMAGE.frame_m, WMS_ROOF_IMAGE.acquired_on) == (None, None, None)


def test_the_building_card_reports_a_local_crop(tmp_path: Path) -> None:
    write_village(tmp_path)
    pool = NamedPool(row=BUILDING_ROW)

    with TestClient(app_with(str(tmp_path), pool=pool)) as client:
        response = client.get(BUILDING_PATH.format(osm_id=LOCAL_ID))

    assert response.status_code == 200
    assert response.json()["roofImage"] == {
        "source": "local",
        "gsdM": 0.05,
        "frameM": 12.8,
        "acquiredOn": "2023-12-05",
    }


def test_the_building_card_reports_the_wms_with_nulls(tmp_path: Path) -> None:
    write_village(tmp_path)
    pool = NamedPool(row=(REMOTE_ID, *BUILDING_ROW[1:]))

    with TestClient(app_with(str(tmp_path), pool=pool)) as client:
        response = client.get(BUILDING_PATH.format(osm_id=REMOTE_ID))

    assert response.json()["roofImage"] == {
        "source": "wms",
        "gsdM": None,
        "frameM": None,
        "acquiredOn": None,
    }


def test_the_roof_image_field_is_always_there(tmp_path: Path) -> None:
    """Front nie musi pytac, czy pole jest — bez konfiguracji jest po prostu `wms`."""
    pool = NamedPool(row=BUILDING_ROW)

    with TestClient(app_with("", pool=pool)) as client:
        body = client.get(BUILDING_PATH.format(osm_id=LOCAL_ID)).json()

    assert body["roofImage"]["source"] == "wms"


# --- /api/villages -----------------------------------------------------------------------------


def test_villages_are_empty_without_configuration() -> None:
    with TestClient(app_with("")) as client:
        response = client.get(VILLAGES_PATH)

    assert response.status_code == 200
    assert response.json() == {"villages": []}


@pytest.mark.parametrize("state", ["missing", "broken"])
def test_villages_are_empty_when_the_data_is_unusable(tmp_path: Path, state: str) -> None:
    directory = tmp_path / "nie-ma"
    if state == "broken":
        directory = tmp_path
        write_village(tmp_path, metadata="\x00 smieci")

    with TestClient(app_with(str(directory))) as client:
        response = client.get(VILLAGES_PATH)

    assert response.status_code == 200
    assert response.json() == {"villages": []}


def test_villages_have_the_shape_the_front_expects(tmp_path: Path) -> None:
    rows = [
        csv_row(LOCAL_ID, f"osm_{LOCAL_ID}_a.png", acquired_on="2023-12-05"),
        csv_row(SECOND_LOCAL_ID, f"osm_{SECOND_LOCAL_ID}_b.png", acquired_on="2023-12-12"),
    ]
    write_village(tmp_path, rows=rows)

    with TestClient(app_with(str(tmp_path))) as client:
        body = client.get(VILLAGES_PATH).json()

    assert body == {
        "villages": [
            {
                "name": "Janikow",
                "folder": "miasteczko1",
                "sw": SW,
                "ne": NE,
                "crops": 2,
                "buildings": 458,
                "gsdM": 0.05,
                "frameM": 12.8,
                "acquiredFrom": "2023-12-05",
                "acquiredTo": "2023-12-12",
            }
        ]
    }


def test_one_flight_date_gives_the_same_bounds_for_both_ends(tmp_path: Path) -> None:
    write_village(tmp_path)

    with TestClient(app_with(str(tmp_path))) as client:
        village = client.get(VILLAGES_PATH).json()["villages"][0]

    assert village["acquiredFrom"] == village["acquiredTo"] == "2023-12-05"


def test_a_village_without_a_boundary_is_not_listed_but_still_serves_crops(tmp_path: Path) -> None:
    """Bez granicy nie ma czego pokazac na mapie, wiec wpisu w spisie nie zmyslamy — zdjecia zostaja."""
    write_village(tmp_path)
    (tmp_path / "miasteczko1" / "boundary.geojson").unlink()
    seen, handler = recording_handler()

    with TestClient(app_with(str(tmp_path), handler=handler)) as client:
        body = client.get(VILLAGES_PATH).json()
        roof = client.get(ROOF_PATH.format(osm_id=LOCAL_ID))

    assert body == {"villages": []}
    assert roof.content == LOCAL_PNG
    assert seen == []


def test_the_villages_setting_is_empty_by_default() -> None:
    """Domyslna wartosc jest w kodzie, a nie na tej maszynie — sciezke wpisuje sie do `.env`."""
    assert Settings.model_fields["villages_dir"].default == ""
