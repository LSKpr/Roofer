import json
from datetime import date

import httpx
import numpy as np
import pytest
from pyproj import Transformer
from rasterio.enums import ColorInterp
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import box, mapping

from app.providers.roof_imagery import CropError, OrthoSource
from app.services.geo import to_4326
from app.services.roof_dataset import (
    CELL_M,
    NEGATIVE,
    POSITIVE,
    Candidate,
    DatasetError,
    accept,
    building_candidates,
    cell_of,
    covered,
    iter_line_features,
    main,
    read_selection,
    scan_registry,
    single_polygon,
)

CENTER = (637164.3645, 486728.9119)
SOURCE_URL = "https://opendata.geoportal.gov.pl/ortofotomapa/83235/83235_1485417_N-34-139-A-c-1-1.tif"
SOURCE = OrthoSource(SOURCE_URL, "N-34-139-A-c-1-1", date(2024, 4, 27), 0.25)


def roof(dx=0.0, dy=0.0, half=6.0):
    return mapping(to_4326(box(CENTER[0] + dx - half, CENTER[1] + dy - half, CENTER[0] + dx + half, CENTER[1] + dy + half)))


def snapshot(path, name, features, declared=None):
    lines = ['{"type":"FeatureCollection","name":' + json.dumps(name) + ',"features":[']
    lines += [json.dumps(feature) + "," for feature in features[:-1]] + [json.dumps(features[-1])]
    lines.append('],"numberReturned":' + str(len(features) if declared is None else declared) + "}")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def registry_feature(identifier, dx=0.0, dy=0.0, half=6.0, geometry=None):
    return {"type": "Feature", "id": identifier, "geometry": geometry if geometry is not None else roof(dx, dy, half), "properties": {"nr_dzialki": "140101_5.0010.269/1"}}


def building_feature(identifier, dx=0.0, dy=0.0, half=6.0, multi=True):
    geometry = roof(dx, dy, half)
    if multi:
        geometry = {"type": "MultiPolygon", "coordinates": [geometry["coordinates"]]}
    return {"type": "Feature", "id": identifier, "properties": {"osm_id": identifier, "type": "house", "name": None}, "geometry": geometry}


def test_snapshot_reader_requires_one_feature_per_line(tmp_path):
    path = tmp_path / "broken.geojson"
    path.write_text('{"type":"FeatureCollection","features":[\n{"type":"Feature",\n"id":"a"}]}', encoding="utf-8")
    with pytest.raises(DatasetError, match="one complete Feature"):
        list(iter_line_features(path))
    geometry_only = tmp_path / "geometry.geojson"
    geometry_only.write_text('{"type":"FeatureCollection","features":[\n{"type":"Polygon","coordinates":[]}]}', encoding="utf-8")
    with pytest.raises(DatasetError, match="one complete Feature"):
        list(iter_line_features(geometry_only))
    plain = tmp_path / "plain.geojson"
    plain.write_text('{"type":"Feature","id":"a"}', encoding="utf-8")
    with pytest.raises(DatasetError, match="FeatureCollection"):
        list(iter_line_features(plain))


def test_reader_accepts_the_snapshot_layout(tmp_path):
    path = snapshot(tmp_path / "ok.geojson", "registry", [registry_feature("a"), registry_feature("b", dx=40)])
    assert [feature["id"] for feature in iter_line_features(path)] == ["a", "b"]


def test_reader_verifies_the_declared_feature_count(tmp_path):
    path = snapshot(tmp_path / "short.geojson", "registry", [registry_feature("a")], declared=9)
    with pytest.raises(DatasetError, match="truncated"):
        list(iter_line_features(path))
    unterminated = tmp_path / "unterminated.geojson"
    unterminated.write_text('{"type":"FeatureCollection","features":[\n' + json.dumps(registry_feature("a")), encoding="utf-8")
    with pytest.raises(DatasetError, match="without the closing feature array"):
        list(iter_line_features(unterminated))


def test_single_polygon_unwraps_only_unambiguous_multipolygons():
    assert single_polygon({"type": "MultiPolygon", "coordinates": [[[[0, 0]]]]})["type"] == "Polygon"
    assert single_polygon({"type": "MultiPolygon", "coordinates": [[[[0, 0]]], [[[1, 1]]]]}) is None
    assert single_polygon({"type": "Point", "coordinates": [0, 0]}) is None


@pytest.mark.parametrize("geometry,reason", [
    (roof(half=1.0), "area_out_of_range"),
    (roof(half=40.0), "area_out_of_range"),
    ({"type": "Polygon", "coordinates": [[[-132310.2, -16621544.7], [-132310.1, -16621544.7], [-132310.1, -16621544.6], [-132310.2, -16621544.7]]]}, "invalid_input"),
])
def test_rejected_candidates_are_counted_by_reason(geometry, reason):
    from collections import Counter

    rejected = Counter()
    assert accept(geometry, 20.0, 1000.0, rejected) is None
    assert rejected[reason] == 1


def test_registry_scan_groups_by_cell_and_keeps_unusable_geometry_for_exclusion(tmp_path):
    path = snapshot(tmp_path / "registry.geojson", "registry", [
        registry_feature("usable"),
        registry_feature("too_small", dx=40, half=1.0),
        registry_feature("nowhere", geometry={"type": "Polygon", "coordinates": [[[-132310.2, -16621544.7], [-132310.1, -16621544.7], [-132310.1, -16621544.6], [-132310.2, -16621544.7]]]}),
    ])
    exclusion, cells, rejected = scan_registry(path, 20.0, 1000.0)
    assert list(cells) == [cell_of(*CENTER)]
    assert cells[cell_of(*CENTER)] == ["usable"]
    assert len(exclusion) == 2
    assert rejected["area_out_of_range"] == 1
    assert rejected["unprojectable_registry_geometry"] == 1


def test_negatives_must_clear_the_exclusion_distance(tmp_path):
    registry = snapshot(tmp_path / "registry.geojson", "registry", [registry_feature("listed")])
    buildings = snapshot(tmp_path / "buildings.geojson", "osm", [
        building_feature("near", dx=20),
        building_feature("far", dx=120),
        building_feature("elsewhere", dx=5 * CELL_M),
    ])
    exclusion, _, _ = scan_registry(registry, 20.0, 1000.0)
    found, rejected = building_candidates(buildings, {cell_of(*CENTER)}, exclusion, 15.0, 10, 20.0, 1000.0, 1)
    assert [candidate.source_id for candidate in found[cell_of(*CENTER)]] == ["far"]
    assert rejected["near_registry_object"] == 1


def test_negative_cap_is_deterministic_for_a_seed(tmp_path):
    buildings = snapshot(tmp_path / "buildings.geojson", "osm", [building_feature(f"b{index}", dx=100 + index * 20) for index in range(9)])
    registry = snapshot(tmp_path / "registry.geojson", "registry", [registry_feature("listed")])
    exclusion, _, _ = scan_registry(registry, 20.0, 1000.0)
    first, _ = building_candidates(buildings, {cell_of(*CENTER)}, exclusion, 15.0, 3, 20.0, 1000.0, 7)
    second, _ = building_candidates(buildings, {cell_of(*CENTER)}, exclusion, 15.0, 3, 20.0, 1000.0, 7)
    other, _ = building_candidates(buildings, {cell_of(*CENTER)}, exclusion, 15.0, 3, 20.0, 1000.0, 8)
    picked = [candidate.source_id for candidate in first[cell_of(*CENTER)]]
    assert len(picked) == 3
    assert picked == [candidate.source_id for candidate in second[cell_of(*CENTER)]]
    assert picked != [candidate.source_id for candidate in other[cell_of(*CENTER)]]


def test_coverage_check_rejects_a_window_crossing_the_sheet_edge():
    candidate = Candidate(POSITIVE, "geoazbest", "1", list(cell_of(*CENTER)), 144.0, [21.0, 52.2], roof(), {})
    inside = (CENTER[0] - 50, CENTER[1] - 50, CENTER[0] + 50, CENTER[1] + 50)
    assert covered(candidate, inside)
    assert not covered(candidate, (CENTER[0] - 50, CENTER[1] - 50, CENTER[0] + 5, CENTER[1] + 50))


def index_html(resolution="0.25", acquired="2024-04-27"):
    values = {"url": SOURCE_URL, "godlo": SOURCE.sheet, "aktualnosc": acquired, "wielkoscPiksela": resolution, "kolor": "RGB"}
    body = ",".join(f"{key}:{json.dumps(value)}" for key, value in values.items())
    return f"<script>var skorOd10cm = [];\nskorOd10cm.push({{{body}}});</script>"


def raster_bytes(resolution=0.25, size_m=400):
    size = round(size_m / resolution)
    data = np.full((3, size, size), 90, dtype="uint8")
    transform = from_origin(CENTER[0] - size_m / 2, CENTER[1] + size_m / 2, resolution, resolution)
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", width=size, height=size, count=3, dtype="uint8", crs="EPSG:2180", transform=transform) as dataset:
            dataset.write(data)
            dataset.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
        return memory.read()


def dataset_client(monkeypatch, raster):
    def handler(request):
        return httpx.Response(200, text=index_html()) if request.url.host == "mapy.geoportal.gov.pl" else httpx.Response(200, content=raster, headers={"Content-Length": str(len(raster))})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))


def test_build_writes_labelled_crops_with_registry_caveats(tmp_path, monkeypatch, capsys):
    dataset_client(monkeypatch, raster_bytes())
    registry = snapshot(tmp_path / "registry.geojson", "registry", [registry_feature(f"budynki_z_azbestem.{index}", dx=index * 25 - 100) for index in range(4)])
    buildings = snapshot(tmp_path / "buildings.geojson", "osm", [building_feature(f"{index}", dx=index * 25 - 100, dy=120) for index in range(4)])
    output = tmp_path / "dataset"
    code = main([
        "--registry", str(registry), "--buildings", str(buildings), "--output", str(output),
        "--positives", "3", "--negatives", "2", "--per-sheet-positives", "3", "--per-sheet-negatives", "2",
        "--max-sheets", "2", "--year", "2024", "--cache-dir", str(tmp_path / "cache"), "--max-download-mb", "8",
    ])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["counts"] == {POSITIVE: 3, NEGATIVE: 2}
    rows = [json.loads(line) for line in (output / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sorted(row["binary_label"] for row in rows if row["status"] == "ok") == [0, 0, 1, 1, 1]
    positive = next(row for row in rows if row.get("class") == POSITIVE)
    assert positive["sheet"] == SOURCE.sheet
    assert positive["native_resolution_m"] == 0.25
    saved = json.loads((output / positive["png"]).with_suffix(".json").read_text(encoding="utf-8"))
    assert saved["output"]["size_px"] == [47, 47]
    assert saved["output"]["resolution_m"] == 0.25
    assert saved["dataset"]["label"] == "listed_in_geoazbest"
    assert saved["source"]["acquisition_date"] == "2024-04-27"
    assert any("declaration register" in warning for warning in saved["warnings"])
    assert any("not confirmed asbestos free" in warning for warning in saved["warnings"])
    assert (output / positive["png"]).read_bytes().startswith(b"\x89PNG")


def test_rerun_resumes_without_duplicating_or_overwriting(tmp_path, monkeypatch, capsys):
    dataset_client(monkeypatch, raster_bytes())
    registry = snapshot(tmp_path / "registry.geojson", "registry", [registry_feature(f"r{index}", dx=index * 25 - 100) for index in range(3)])
    buildings = snapshot(tmp_path / "buildings.geojson", "osm", [building_feature(f"{index}", dx=index * 25 - 100, dy=120) for index in range(3)])
    arguments = [
        "--registry", str(registry), "--buildings", str(buildings), "--output", str(tmp_path / "dataset"),
        "--positives", "2", "--negatives", "1", "--per-sheet-positives", "2", "--per-sheet-negatives", "1",
        "--max-sheets", "1", "--cache-dir", str(tmp_path / "cache"), "--max-download-mb", "8",
    ]
    assert main(arguments) == 0
    capsys.readouterr()
    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["counts"] == {POSITIVE: 2, NEGATIVE: 1}
    pngs = list((tmp_path / "dataset").rglob("*.png"))
    assert len(pngs) == 3


def test_selection_is_reused_only_for_identical_rules(tmp_path, monkeypatch, capsys):
    dataset_client(monkeypatch, raster_bytes())
    registry = snapshot(tmp_path / "registry.geojson", "registry", [registry_feature("r0"), registry_feature("r1", dx=40)])
    buildings = snapshot(tmp_path / "buildings.geojson", "osm", [building_feature("0", dy=120)])
    base = ["--registry", str(registry), "--buildings", str(buildings), "--output", str(tmp_path / "dataset"), "--max-sheets", "1", "--per-sheet-positives", "1", "--per-sheet-negatives", "1", "--select-only"]
    assert main(base) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "selected"
    candidates, meta = read_selection(tmp_path / "dataset" / "selection.jsonl")
    assert meta["negative_rule"].startswith("OSM building at least 15 m")
    assert {candidate.dataset_class for candidate in candidates} == {POSITIVE, NEGATIVE}
    assert main(base) == 0
    assert main(base + ["--exclusion-m", "50"]) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "dataset_error"


def test_sheet_without_the_pinned_resolution_is_skipped_not_substituted(tmp_path, monkeypatch, capsys):
    def handler(request):
        return httpx.Response(200, text=index_html(resolution="0.05")) if request.url.host == "mapy.geoportal.gov.pl" else httpx.Response(200, content=raster_bytes(0.05, 100))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    registry = snapshot(tmp_path / "registry.geojson", "registry", [registry_feature("r0")])
    buildings = snapshot(tmp_path / "buildings.geojson", "osm", [building_feature("0", dy=120)])
    output = tmp_path / "dataset"
    assert main([
        "--registry", str(registry), "--buildings", str(buildings), "--output", str(output),
        "--max-sheets", "1", "--per-sheet-positives", "1", "--per-sheet-negatives", "1",
        "--cache-dir", str(tmp_path / "cache"), "--max-download-mb", "8",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["counts"] == {"sheet_no_coverage": 1}
    assert not list(output.rglob("*.png"))
