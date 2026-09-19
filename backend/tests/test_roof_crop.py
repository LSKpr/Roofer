import io
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.enums import ColorInterp
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile
from rasterio.transform import from_origin, xy
from shapely.geometry import Polygon, box, mapping

from app.providers.roof_imagery import CropError, OrthoSource, discover_sources, download_source, parse_sources
from app.services.geo import to_4326
from app.services.roof_crop import build_window, crop_raster, export_crop, main, run_crop

CENTER = (637164.3645, 486728.9119)
SOURCE_URL = "https://opendata.geoportal.gov.pl/ortofotomapa/83235/83235_1485417_N-34-139-A-c-1-1.tif"
SOURCE = OrthoSource(SOURCE_URL, "N-34-139-A-c-1-1", date(2025, 4, 27), 0.05)
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "crop_roof.py"


def roof(polygon=None):
    geometry = polygon if polygon is not None else box(CENTER[0] - 10, CENTER[1] - 8, CENTER[0] + 10, CENTER[1] + 8)
    return mapping(to_4326(geometry))


def index_html(records=None):
    records = records if records is not None else [(SOURCE_URL, "2025-04-27", "0.05", "RGB")]
    rows = []
    for url, acquired, resolution, color in records:
        values = {"url": url, "godlo": "N-34-139-A-c-1-1", "aktualnosc": acquired, "wielkoscPiksela": resolution, "kolor": color}
        body = ",".join(f"{key}:{json.dumps(value)}" for key, value in values.items())
        rows.append(f"skorDo5cm.push({{{body}}});")
    return "<script>var skorDo5cm = []; var skor510cm = []; var skorOd10cm = [];\n" + "\n".join(rows) + "</script>"


def raster_bytes(resolution=0.05, nodata=False, shifted=False, crs="EPSG:2180"):
    size = round(20 / resolution)
    data = np.full((3, size, size), 80, dtype="uint8")
    data[1] = 120
    data[2] = 160
    if nodata:
        data[:, size // 2, size // 2] = 0
    center = Transformer.from_crs("EPSG:2180", crs, always_xy=True).transform(*CENTER)
    transform = from_origin(center[0] - 10 + (100 if shifted else 0), center[1] + 10, resolution, resolution)
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", width=size, height=size, count=3, dtype="uint8", crs=crs, transform=transform, nodata=0 if nodata else None) as dataset:
            dataset.write(data)
            dataset.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
        return memory.read()


def raster_file(tmp_path, **kwargs):
    path = tmp_path / "source.tif"
    path.write_bytes(raster_bytes(**kwargs))
    return path


def test_window_uses_surface_centroid_and_exact_metric_grid():
    polygon = Polygon([(CENTER[0], CENTER[1]), (CENTER[0] + 30, CENTER[1]), (CENTER[0], CENTER[1] + 18)])
    window = build_window(roof(polygon))
    assert window.center_2180 == pytest.approx((CENTER[0] + 10, CENTER[1] + 6), abs=1e-6)
    assert window.bounds[2] - window.bounds[0] == pytest.approx(11.75)
    assert window.bounds[3] - window.bounds[1] == pytest.approx(11.75)
    assert xy(window.transform, 23, 23) == pytest.approx(window.center_2180)
    assert (window.transform.a, window.transform.e) == (0.25, -0.25)


def test_feature_and_polygon_have_identical_windows():
    geometry = roof()
    assert build_window({"type": "Feature", "geometry": geometry, "properties": {}}).bounds == build_window(geometry).bounds


def test_hole_changes_centroid_using_surface_area():
    outer = box(CENTER[0] - 20, CENTER[1] - 20, CENTER[0] + 20, CENTER[1] + 20)
    hole = box(CENTER[0] + 5, CENTER[1] + 5, CENTER[0] + 15, CENTER[1] + 15)
    polygon = Polygon(outer.exterior.coords, [hole.exterior.coords])
    window = build_window(roof(polygon))
    assert window.center_2180 == pytest.approx((polygon.centroid.x, polygon.centroid.y), abs=1e-6)


def test_centroid_in_courtyard_requires_review():
    outer = box(CENTER[0] - 20, CENTER[1] - 20, CENTER[0] + 20, CENTER[1] + 20)
    hole = box(CENTER[0] - 5, CENTER[1] - 5, CENTER[0] + 5, CENTER[1] + 5)
    with pytest.raises(CropError, match="centroid") as error:
        build_window(roof(Polygon(outer.exterior.coords, [hole.exterior.coords])))
    assert error.value.status == "needs_review"


@pytest.mark.parametrize("payload", [
    {"type": "FeatureCollection", "features": []},
    {"type": "MultiPolygon", "coordinates": []},
    {"type": "Feature", "geometry": None},
    {"type": "Polygon", "coordinates": [[[10**400, 52], [21, 52], [21, 53], [10**400, 52]]]},
    {"type": "Polygon", "coordinates": [[[21, 52], [21.001, 52], [21.001, 52.001]]]},
    {"type": "Polygon", "coordinates": [[[52, 21], [52.001, 21], [52, 21.001], [52, 21]]]},
    {"type": "Polygon", "coordinates": [[[21, 52], [float("nan"), 52], [21, 52.001], [21, 52]]]},
    {"type": "Polygon", "coordinates": [[[21, 52], [21.001, 52.001], [21, 52.001], [21.001, 52], [21, 52]]]},
])
def test_invalid_geojson_is_rejected(payload):
    with pytest.raises(CropError):
        build_window(payload)


def test_declared_non_wgs84_crs_is_rejected():
    payload = dict(roof(), crs={"type": "name", "properties": {"name": "EPSG:2180"}})
    with pytest.raises(CropError, match="CRS"):
        build_window(payload)


def test_sources_sorted_by_native_resolution_then_date_and_rgb_only():
    records = [
        (SOURCE_URL.replace("83235/", "1/"), "2026-01-01", "0.25", "RGB"),
        (SOURCE_URL.replace("83235/", "2/"), "2024-04-01", "0.05", "RGB"),
        (SOURCE_URL, "2025-04-27", "0.05", "RGB"),
        (SOURCE_URL.replace("83235/", "4/"), "2026-01-01", "0.03", "CIR"),
    ]
    sources = parse_sources(index_html(records))
    assert [source.resolution_m for source in sources] == [0.05, 0.05, 0.25]
    assert sources[0] == SOURCE
    assert parse_sources(index_html(records), year=2024)[0].acquisition_date.year == 2024


@pytest.mark.parametrize("html,status", [
    ("<ServiceExceptionReport>down</ServiceExceptionReport>", "source_unavailable"),
    ("<html>Changed response format</html>", "invalid_metadata"),
    (index_html([]), "no_coverage"),
    (index_html([(SOURCE_URL, "2025-04-27", "0.5", "RGB")]), "insufficient_resolution"),
    (index_html([(SOURCE_URL, "unknown", "0.05", "RGB")]), "invalid_metadata"),
    (index_html([("https://example.test/image.tif", "2025-04-27", "0.05", "RGB")]), "invalid_metadata"),
])
def test_metadata_failures_are_explicit(html, status):
    with pytest.raises(CropError) as error:
        parse_sources(html)
    assert error.value.status == status


def test_metadata_does_not_execute_javascript():
    html = index_html().replace('wielkoscPiksela:"0.05"', 'wielkoscPiksela:alert("bad")')
    with pytest.raises(CropError):
        parse_sources(html)


def test_discovery_uses_lat_lon_axis_order_for_wms_130():
    def handler(request):
        params = request.url.params
        assert params["REQUEST"] == "GetFeatureInfo"
        assert params["CRS"] == "EPSG:4326"
        south, west, north, east = map(float, params["BBOX"].split(","))
        assert south < 52.2295 < north and west < 21.009 < east
        assert params["INFO_FORMAT"] == "text/html"
        return httpx.Response(200, text=index_html())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert discover_sources(client, 21.009, 52.2295)[0] == SOURCE


def test_download_cache_is_reused_and_integrity_checked(tmp_path):
    content = raster_bytes()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=content, headers={"Content-Length": str(len(content))})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = download_source(client, SOURCE, tmp_path, len(content) + 1)
        second = download_source(client, SOURCE, tmp_path, len(content) + 1)
        assert first.path == second.path
        assert first.sha256 == second.sha256
        assert len(calls) == 1
        first.path.write_bytes(b"corrupt")
        with pytest.raises(CropError) as error:
            download_source(client, SOURCE, tmp_path, len(content) + 1)
        assert error.value.status == "invalid_cache"


@pytest.mark.parametrize("with_length", [True, False])
def test_download_limit_leaves_no_partial_cache(tmp_path, with_length):
    content = raster_bytes()

    def handler(request):
        response = httpx.Response(200, content=content)
        if not with_length:
            del response.headers["content-length"]
        return response

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CropError) as error:
            download_source(client, SOURCE, tmp_path, 100)
        assert error.value.status == "download_limit"
    assert not list(tmp_path.iterdir())


def test_network_failure_is_not_no_coverage(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        with pytest.raises(CropError) as error:
            download_source(client, SOURCE, tmp_path, 1000)
        assert error.value.status == "source_unavailable"


def test_crop_is_rgb_47_by_47_without_color_normalization(tmp_path):
    png, raster_metadata = crop_raster(raster_file(tmp_path), build_window(roof()), SOURCE)
    with pytest.warns(NotGeoreferencedWarning), MemoryFile(png) as memory, memory.open() as image:
        assert (image.width, image.height, image.count) == (47, 47, 3)
        assert image.dtypes == ("uint8",) * 3
        assert image.read()[:, 23, 23].tolist() == [80, 120, 160]
    assert raster_metadata["native_resolution_m"] == pytest.approx([0.05, 0.05])


@pytest.mark.parametrize("kwargs,status", [
    ({"nodata": True}, "no_coverage"),
    ({"shifted": True}, "no_coverage"),
    ({"resolution": 0.5}, "insufficient_resolution"),
    ({"resolution": 0.1}, "invalid_metadata"),
])
def test_raster_must_cover_window_with_verified_native_resolution(tmp_path, kwargs, status):
    with pytest.raises(CropError) as error:
        crop_raster(raster_file(tmp_path, **kwargs), build_window(roof()), SOURCE)
    assert error.value.status == status


def test_end_to_end_writes_png_and_provenance(tmp_path):
    content = raster_bytes()

    def handler(request):
        return httpx.Response(200, text=index_html()) if request.url.host == "mapy.geoportal.gov.pl" else httpx.Response(200, content=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        png, metadata = run_crop(roof(), client, tmp_path / "cache", max_download_bytes=len(content) + 1)
    prefix = tmp_path / "output" / "roof"
    export_crop(prefix, png, metadata)
    assert prefix.with_suffix(".png").read_bytes().startswith(b"\x89PNG")
    saved = json.loads(prefix.with_suffix(".json").read_text())
    assert saved["status"] == "ok"
    assert saved["output"]["size_px"] == [47, 47]
    assert saved["output"]["resolution_m"] == 0.25
    assert saved["source"]["url"] == SOURCE_URL
    assert saved["source"]["acquisition_date"] == "2025-04-27"
    assert len(saved["source"]["sha256"]) == 64
    assert saved["warnings"]
    with pytest.raises(CropError) as error:
        export_crop(prefix, png, metadata)
    assert error.value.status == "output_exists"


def test_cli_handles_stdin_and_invalid_json_without_traceback(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "--input", "-", "--output", str(tmp_path / "roof")], input="not json", capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stderr)["status"] == "invalid_input"
    assert "Traceback" not in result.stderr


def test_cli_help_describes_limits_and_cache():
    result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--max-download-mb" in result.stdout
    assert "--cache-dir" in result.stdout
    assert "--year" in result.stdout


def test_crop_reprojects_polish_zone_2000_to_2180(tmp_path):
    png, metadata = crop_raster(raster_file(tmp_path, crs="EPSG:2178"), build_window(roof()), SOURCE)
    assert metadata["crs"] == "EPSG:2178"
    with pytest.warns(NotGeoreferencedWarning), MemoryFile(png) as memory, memory.open() as image:
        assert np.all(image.read()[0] == 80)
        assert np.all(image.read()[1] == 120)


def test_area_resampling_averages_detail_instead_of_aliasing(tmp_path):
    path = raster_file(tmp_path)
    with rasterio.open(path, "r+") as dataset:
        checkerboard = ((np.indices((dataset.height, dataset.width)).sum(axis=0) % 2) * 255).astype("uint8")
        dataset.write(np.stack([checkerboard] * 3))
    png, _ = crop_raster(path, build_window(roof()), SOURCE)
    with pytest.warns(NotGeoreferencedWarning), MemoryFile(png) as memory, memory.open() as image:
        assert image.read().min() >= 120
        assert image.read().max() <= 135


def test_small_roof_keeps_surroundings_and_native_25cm_is_allowed(tmp_path):
    geometry = roof(box(CENTER[0] - 1, CENTER[1] - 1, CENTER[0] + 1, CENTER[1] + 1))
    png, _ = crop_raster(raster_file(tmp_path, resolution=0.25), build_window(geometry), replace(SOURCE, resolution_m=0.25))
    with pytest.warns(NotGeoreferencedWarning), MemoryFile(png) as memory, memory.open() as image:
        assert np.all(image.read()[0] == 80)
        assert image.read()[:, 0, 0].tolist() == [80, 120, 160]


@pytest.mark.parametrize("response,status", [
    (httpx.Response(200, text="<html>failure</html>"), "invalid_raster"),
    (httpx.Response(200, content=b"II*\\x00truncated", headers={"content-length": "999"}), "source_unavailable"),
    (httpx.Response(302, headers={"location": "https://example.test/redirect"}), "source_unavailable"),
])
def test_invalid_download_is_not_cached(tmp_path, response, status):
    with httpx.Client(transport=httpx.MockTransport(lambda request: response)) as client:
        with pytest.raises(CropError) as error:
            download_source(client, SOURCE, tmp_path, 10000)
    assert error.value.status == status
    assert not list(tmp_path.iterdir())


def test_cli_accepts_geojson_from_js_on_stdin(tmp_path, monkeypatch, capsys):
    content = raster_bytes()
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=index_html()) if request.url.host == "mapy.geoportal.gov.pl" else httpx.Response(200, content=content)))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(roof()).encode())))
    result = main(["--input", "-", "--output", str(tmp_path / "roof"), "--cache-dir", str(tmp_path / "cache")])
    assert result == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    assert (tmp_path / "roof.png").is_file()
    assert (tmp_path / "roof.json").is_file()


@pytest.mark.skipif(os.getenv("ROOF_CROP_LIVE_TEST") != "1", reason="Opt-in GUGiK download (one original RGB sheet, up to 128 MiB)")
def test_live_original_geotiff_crop(tmp_path):
    with httpx.Client(timeout=60) as client:
        png, metadata = run_crop(roof(), client, tmp_path / "cache", year=2024, max_download_bytes=128 * 1024 * 1024)
    assert png.startswith(b"\x89PNG")
    assert metadata["source"]["acquisition_date"].startswith("2024")
    assert metadata["raster"]["native_resolution_m"] == pytest.approx([0.25, 0.25])
    assert metadata["output"]["size_px"] == [47, 47]
