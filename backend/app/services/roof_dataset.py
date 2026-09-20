import argparse
import json
import logging
import math
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx
import orjson
import rasterio
from pyproj import Transformer
from rasterio.errors import RasterioError
from rasterio.warp import transform_bounds
from shapely.geometry import box, shape
from shapely.strtree import STRtree

from app.providers.roof_imagery import CachedRaster, CropError, OrthoSource, discover_sources, download_source
from app.services.geo import to_2180
from app.services.roof_crop import SIDE_M, build_window, crop_metadata, crop_raster, default_cache_dir, export_crop, output_paths

CELL_M = 2000.0
HEADER_PATTERN = re.compile(rb'^\{\s*"type"\s*:\s*"FeatureCollection".*"features"\s*:\s*\[\s*$', re.DOTALL)
POSITIVE = "asbestos"
NEGATIVE = "clean"
CLASS_LABELS = {POSITIVE: "listed_in_geoazbest", NEGATIVE: "absent_from_geoazbest"}
SELECTION = "fixed acquisition year and native pixel chosen for dataset uniformity, newest sheet of that year; not the smallest available pixel"
TO_4326 = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)
logger = logging.getLogger("roofer.dataset")


class DatasetError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    dataset_class: str
    source: str
    source_id: str
    cell: list[int]
    area_m2: float
    center_4326: list[float]
    geometry: dict[str, Any]
    attributes: dict[str, Any]


def iter_line_features(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("rb") as handle:
        if HEADER_PATTERN.match(handle.readline().strip()) is None:
            raise DatasetError(f"{path.name} must be a snapshot FeatureCollection whose header line ends with \"features\": [.")
        count = 0
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(b"]"):
                declared = footer_count(path, line)
                if declared is not None and declared != count:
                    raise DatasetError(f"{path.name} declares {declared} features but holds {count}; the snapshot is truncated.")
                return
            if line.endswith(b","):
                line = line[:-1]
            try:
                feature = orjson.loads(line)
            except orjson.JSONDecodeError as error:
                raise DatasetError(f"{path.name} holds a line that is not one complete Feature; the snapshot format changed.") from error
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise DatasetError(f"{path.name} holds a line that is not one complete Feature; the snapshot format changed.")
            count += 1
            yield feature
        raise DatasetError(f"{path.name} ends without the closing feature array; the snapshot is truncated.")


def footer_count(path: Path, line: bytes) -> int | None:
    rest = line[1:].lstrip().lstrip(b",")
    try:
        footer = orjson.loads(b"{" + rest) if rest != b"}" else {}
    except orjson.JSONDecodeError as error:
        raise DatasetError(f"{path.name} has an unreadable closing line; the snapshot format changed.") from error
    declared = footer.get("numberReturned")
    if declared is not None and not isinstance(declared, int):
        raise DatasetError(f"{path.name} declares a non-integer feature count.")
    return declared


def cell_of(x: float, y: float) -> tuple[int, int]:
    return math.floor(x / CELL_M), math.floor(y / CELL_M)


def cell_center_4326(cell: tuple[int, int]) -> tuple[float, float]:
    return TO_4326.transform((cell[0] + 0.5) * CELL_M, (cell[1] + 0.5) * CELL_M)


def single_polygon(geometry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") == "Polygon":
        return geometry
    if geometry.get("type") == "MultiPolygon" and len(geometry.get("coordinates") or []) == 1:
        return {"type": "Polygon", "coordinates": geometry["coordinates"][0]}
    return None


def accept(geometry: dict[str, Any], min_area: float, max_area: float, rejected: Counter) -> tuple[Any, float] | None:
    polygon = single_polygon(geometry)
    if polygon is None:
        rejected["not_a_single_polygon"] += 1
        return None
    try:
        window = build_window(polygon)
    except CropError as error:
        rejected[error.status] += 1
        return None
    area = window.roof.area
    if not min_area <= area <= max_area:
        rejected["area_out_of_range"] += 1
        return None
    return window, area


def scan_registry(path: Path, min_area: float, max_area: float) -> tuple[list[Any], dict[tuple[int, int], list[str]], Counter]:
    exclusion: list[Any] = []
    cells: dict[tuple[int, int], list[str]] = defaultdict(list)
    rejected: Counter = Counter()
    for feature in iter_line_features(path):
        geometry = feature.get("geometry")
        if isinstance(geometry, dict) and geometry.get("coordinates"):
            try:
                projected = to_2180(shape(geometry))
            except (ValueError, TypeError):
                projected = None
            if projected is not None and projected.is_valid and all(math.isfinite(value) for value in projected.bounds):
                exclusion.append(projected)
            else:
                rejected["unprojectable_registry_geometry"] += 1
        accepted = accept(geometry, min_area, max_area, rejected)
        if accepted is None:
            continue
        window, _ = accepted
        cells[cell_of(*window.center_2180)].append(str(feature.get("id")))
    if not exclusion:
        raise DatasetError("The registry snapshot yielded no usable geometry.")
    return exclusion, cells, rejected


def choose_cells(cells: dict[tuple[int, int], list[str]], max_sheets: int, per_sheet: int) -> list[tuple[int, int]]:
    ranked = sorted(cells, key=lambda cell: (-len(cells[cell]), cell))
    return [cell for cell in ranked if len(cells[cell]) >= per_sheet][:max_sheets]


def registry_candidates(path: Path, wanted: dict[str, tuple[int, int]], min_area: float, max_area: float) -> dict[tuple[int, int], list[Candidate]]:
    found: dict[tuple[int, int], list[Candidate]] = defaultdict(list)
    rejected: Counter = Counter()
    for feature in iter_line_features(path):
        source_id = str(feature.get("id"))
        cell = wanted.get(source_id)
        if cell is None:
            continue
        accepted = accept(feature.get("geometry"), min_area, max_area, rejected)
        if accepted is None:
            continue
        window, area = accepted
        properties = feature.get("properties") or {}
        found[cell].append(Candidate(POSITIVE, "geoazbest", source_id, list(cell), area, list(window.center_4326), single_polygon(feature["geometry"]), {"nr_dzialki": properties.get("nr_dzialki")}))
    return found


def building_candidates(path: Path, cells: set[tuple[int, int]], exclusion: list[Any], min_distance: float, cap: int, min_area: float, max_area: float, seed: int) -> tuple[dict[tuple[int, int], list[Candidate]], Counter]:
    tree = STRtree(exclusion)
    found: dict[tuple[int, int], list[Candidate]] = defaultdict(list)
    seen: Counter = Counter()
    rejected: Counter = Counter()
    rng = random.Random(seed)
    for feature in iter_line_features(path):
        polygon = single_polygon(feature.get("geometry"))
        if polygon is None:
            rejected["not_a_single_polygon"] += 1
            continue
        ring = polygon["coordinates"][0]
        longitudes = [position[0] for position in ring]
        latitudes = [position[1] for position in ring]
        try:
            x, y = to_2180(box(min(longitudes), min(latitudes), max(longitudes), max(latitudes))).centroid.coords[0]
        except (ValueError, TypeError):
            rejected["unprojectable_building"] += 1
            continue
        if not (math.isfinite(x) and math.isfinite(y)) or cell_of(x, y) not in cells:
            continue
        accepted = accept(polygon, min_area, max_area, rejected)
        if accepted is None:
            continue
        window, area = accepted
        cell = cell_of(*window.center_2180)
        if cell not in cells:
            continue
        minx, miny, maxx, maxy = window.roof.bounds
        neighbourhood = box(minx - min_distance, miny - min_distance, maxx + min_distance, maxy + min_distance)
        if any(exclusion[index].distance(window.roof) < min_distance for index in tree.query(neighbourhood)):
            rejected["near_registry_object"] += 1
            continue
        properties = feature.get("properties") or {}
        candidate = Candidate(NEGATIVE, "osm", str(properties.get("osm_id") or feature.get("id")), list(cell), area, list(window.center_4326), polygon, {"type": properties.get("type"), "name": properties.get("name")})
        seen[cell] += 1
        bucket = found[cell]
        if len(bucket) < cap:
            bucket.append(candidate)
        else:
            position = rng.randrange(seen[cell])
            if position < cap:
                bucket[position] = candidate
    return found, rejected


def write_selection(path: Path, candidates: list[Candidate], meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps({"selection_meta": meta}, ensure_ascii=False) + "\n")
        for candidate in candidates:
            stream.write(json.dumps(asdict(candidate), ensure_ascii=False) + "\n")


def read_selection(path: Path) -> tuple[list[Candidate], dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        header = json.loads(stream.readline())
        if "selection_meta" not in header:
            raise DatasetError("Selection file is missing its header record.")
        return [Candidate(**json.loads(line)) for line in stream if line.strip()], header["selection_meta"]


def select(registry: Path, buildings: Path, args: argparse.Namespace) -> list[Candidate]:
    logger.info("Scanning the registry snapshot for eligible roofs.")
    exclusion, registry_cells, registry_rejected = scan_registry(registry, args.min_area, args.max_area)
    cells = choose_cells(registry_cells, args.max_sheets, args.per_sheet_positives)
    if not cells:
        raise DatasetError("No 2 km cell holds enough registry objects for one sheet; lower --per-sheet-positives.")
    logger.info("Registry: %d usable objects, %d cells; using %d cells (%d..%d objects per cell). Rejected: %s", sum(len(ids) for ids in registry_cells.values()), len(registry_cells), len(cells), len(registry_cells[cells[0]]), len(registry_cells[cells[-1]]), dict(registry_rejected))
    rng = random.Random(args.seed)
    wanted: dict[str, tuple[int, int]] = {}
    for cell in cells:
        identifiers = sorted(registry_cells[cell])
        for source_id in rng.sample(identifiers, min(len(identifiers), args.per_sheet_positives * 2)):
            wanted[source_id] = cell
    logger.info("Reading %d registry geometries.", len(wanted))
    positives = registry_candidates(registry, wanted, args.min_area, args.max_area)
    logger.info("Scanning the building snapshot for negatives at least %.0f m from any registry object.", args.exclusion_m)
    negatives, building_rejected = building_candidates(buildings, set(cells), exclusion, args.exclusion_m, args.per_sheet_negatives * 2, args.min_area, args.max_area, args.seed)
    logger.info("Negatives: %d candidates in %d cells. Rejected: %s", sum(len(items) for items in negatives.values()), len(negatives), dict(building_rejected))
    ordered: list[Candidate] = []
    for cell in cells:
        ordered.extend(sorted(positives.get(cell, []), key=lambda candidate: candidate.source_id))
        ordered.extend(sorted(negatives.get(cell, []), key=lambda candidate: candidate.source_id))
    return ordered


def sheet_for_cell(client: httpx.Client, cell: tuple[int, int], year: int, resolution: float) -> OrthoSource:
    longitude, latitude = cell_center_4326(cell)
    sources = [source for source in discover_sources(client, longitude, latitude, year=year) if math.isclose(source.resolution_m, resolution, rel_tol=1e-9)]
    if not sources:
        raise CropError("no_coverage", f"No RGB sheet with {resolution} m native pixel from {year} covers this cell.")
    return sources[0]


def sheet_bounds_2180(path: Path) -> tuple[float, float, float, float]:
    try:
        with rasterio.open(path, OVERVIEW_LEVEL="NONE") as dataset:
            if dataset.crs is None:
                raise CropError("invalid_raster", "Original raster has no CRS.")
            return transform_bounds(dataset.crs, "EPSG:2180", *dataset.bounds, densify_pts=21)
    except RasterioError as error:
        raise CropError("invalid_raster", "Could not read the original GeoTIFF bounds.") from error


def covered(candidate: Candidate, bounds: tuple[float, float, float, float]) -> bool:
    x, y = to_2180(shape(candidate.geometry)).centroid.coords[0]
    half = SIDE_M / 2
    return bounds[0] <= x - half and x + half <= bounds[2] and bounds[1] <= y - half and y + half <= bounds[3]


def crop_candidate(candidate: Candidate, cached: CachedRaster, source: OrthoSource, output: Path, year: int, meta: dict[str, Any]) -> dict[str, Any]:
    prefix = output / candidate.dataset_class / source.sheet / f"{candidate.source}-{candidate.source_id}"
    window = build_window(candidate.geometry)
    png, raster_metadata = crop_raster(cached.path, window, source)
    metadata = crop_metadata(window, source, cached, raster_metadata, year, SELECTION)
    metadata["dataset"] = {
        "class": candidate.dataset_class,
        "label": CLASS_LABELS[candidate.dataset_class],
        "binary_label": 1 if candidate.dataset_class == POSITIVE else 0,
        "geometry_source": candidate.source,
        "source_id": candidate.source_id,
        "footprint_area_m2": candidate.area_m2,
        "cell_2km": candidate.cell,
        "attributes": candidate.attributes,
        "rules": meta,
    }
    metadata["warnings"] = metadata["warnings"] + [
        "GeoAzbest is a declaration register of asbestos products remaining for disposal, not a verified survey; entries can be stale and the public layer carries no dates.",
        "The registry describes asbestos in the structure of a building, which is usually but not necessarily the roof covering.",
        "A building absent from the registry is only unlisted; it is not confirmed asbestos free.",
    ]
    export_crop(prefix, png, metadata)
    return {"png": output_paths(prefix)[0].relative_to(output).as_posix(), "acquisition_date": source.acquisition_date.isoformat(), "sheet": source.sheet, "native_resolution_m": source.resolution_m}


def build(candidates: list[Candidate], args: argparse.Namespace, meta: dict[str, Any]) -> Counter:
    by_cell: dict[tuple[int, int], list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_cell[tuple(candidate.cell)].append(candidate)
    manifest_path = args.output / "manifest.jsonl"
    done: set[tuple[str, str]] = set()
    counts: Counter = Counter()
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row.get("status") == "ok":
                    done.add((row["class"], row["source_id"]))
                    counts[row["class"]] += 1
        logger.info("Resuming: %d crops already recorded (%s).", len(done), dict(counts))
    args.output.mkdir(parents=True, exist_ok=True)
    targets = {POSITIVE: args.positives, NEGATIVE: args.negatives}
    per_sheet = {POSITIVE: args.per_sheet_positives, NEGATIVE: args.per_sheet_negatives}
    with manifest_path.open("a", encoding="utf-8") as manifest, httpx.Client(timeout=args.timeout, follow_redirects=False, headers={"User-Agent": "Roofer-roof-dataset/1.0"}) as client:
        def record(row: dict[str, Any]) -> None:
            manifest.write(json.dumps(row, ensure_ascii=False) + "\n")
            manifest.flush()

        for index, cell in enumerate(sorted(by_cell, key=lambda item: -len(by_cell[item])), 1):
            if all(counts[name] >= targets[name] for name in targets):
                break
            try:
                source = sheet_for_cell(client, cell, args.year, args.native_resolution)
                cached = download_source(client, source, args.cache_dir, int(args.max_download_mb * 1024**2))
                bounds = sheet_bounds_2180(cached.path)
            except CropError as error:
                counts["sheet_" + error.status] += 1
                record({"status": error.status, "detail": str(error), "cell_2km": list(cell)})
                logger.warning("Cell %s skipped: %s (%s)", cell, error.status, error)
                continue
            logger.info("Sheet %d/%d %s (%s, %.0f MiB) for cell %s; have %d/%d positives, %d/%d negatives.", index, len(by_cell), source.sheet, source.acquisition_date, cached.size_bytes / 1024**2, cell, counts[POSITIVE], targets[POSITIVE], counts[NEGATIVE], targets[NEGATIVE])
            for name in (POSITIVE, NEGATIVE):
                produced = 0
                for candidate in by_cell[cell]:
                    if candidate.dataset_class != name or produced >= per_sheet[name] or counts[name] >= targets[name]:
                        continue
                    if (name, candidate.source_id) in done or output_paths(args.output / name / source.sheet / f"{candidate.source}-{candidate.source_id}")[0].exists():
                        continue
                    if not covered(candidate, bounds):
                        counts["outside_sheet"] += 1
                        continue
                    try:
                        row = crop_candidate(candidate, cached, source, args.output, args.year, meta)
                    except CropError as error:
                        counts[error.status] += 1
                        record({"status": error.status, "detail": str(error), "class": name, "source_id": candidate.source_id, "cell_2km": list(cell)})
                        continue
                    counts[name] += 1
                    produced += 1
                    record({
                        "status": "ok", "class": name, "binary_label": 1 if name == POSITIVE else 0, "label": CLASS_LABELS[name],
                        "geometry_source": candidate.source, "source_id": candidate.source_id, "cell_2km": list(cell),
                        "center_lon_lat": candidate.center_4326, "footprint_area_m2": round(candidate.area_m2, 2),
                        "attributes": candidate.attributes, **row,
                    })
            if args.delete_sheets:
                cached.path.unlink(missing_ok=True)
                cached.path.with_suffix(".json").unlink(missing_ok=True)
    return counts


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a labelled roof-crop dataset: GeoAzbest registry roofs as positives and OSM buildings far from any registry object as negatives, cropped to RGB 47x47 at 0.25 m/px from original GUGiK GeoTIFFs.")
    parser.add_argument("--registry", type=Path, required=True, help="GeoAzbest snapshot GeoJSON (one feature per line)")
    parser.add_argument("--buildings", type=Path, required=True, help="OSM buildings snapshot GeoJSON (one feature per line)")
    parser.add_argument("--output", type=Path, required=True, help="Dataset directory; existing crops are never overwritten")
    parser.add_argument("--selection", type=Path, help="Selection JSONL; written when missing and reused afterwards (default: OUTPUT/selection.jsonl)")
    parser.add_argument("--positives", type=int, default=5000)
    parser.add_argument("--negatives", type=int, default=10000)
    parser.add_argument("--per-sheet-positives", type=int, default=60)
    parser.add_argument("--per-sheet-negatives", type=int, default=120)
    parser.add_argument("--max-sheets", type=int, default=160, help="Upper bound on 2 km cells, i.e. on downloaded originals")
    parser.add_argument("--year", type=int, default=2024, help="Acquisition year pinned for the whole dataset")
    parser.add_argument("--native-resolution", type=float, default=0.25, help="Required native pixel of every source sheet")
    parser.add_argument("--exclusion-m", type=float, default=15.0, help="Minimum distance from a negative to any registry object")
    parser.add_argument("--min-area", type=float, default=20.0)
    parser.add_argument("--max-area", type=float, default=1000.0)
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    parser.add_argument("--max-download-mb", type=float, default=256.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--delete-sheets", action="store_true", help="Delete each original after its crops to cap disk use")
    parser.add_argument("--select-only", action="store_true", help="Write the selection and stop before downloading imagery")
    args = parser.parse_args(argv)
    if args.selection is None:
        args.selection = args.output / "selection.jsonl"
    if min(args.positives, args.negatives, args.per_sheet_positives, args.per_sheet_negatives, args.max_sheets) <= 0:
        parser.error("Counts must be positive.")
    if args.min_area <= 0 or args.max_area <= args.min_area or args.exclusion_m < 0 or args.native_resolution <= 0:
        parser.error("Area range, exclusion distance and native resolution must be sensible.")
    if not 1900 <= args.year <= datetime.now(timezone.utc).year:
        parser.error("Year must be between 1900 and the current year.")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    meta = {
        "positive_rule": "polygon present in the GeoAzbest wfs:budynki_z_azbestem layer",
        "negative_rule": f"OSM building at least {args.exclusion_m:.0f} m from every registry polygon",
        "footprint_area_m2_range": [args.min_area, args.max_area],
        "imagery": {"year": args.year, "native_resolution_m": args.native_resolution},
        "seed": args.seed,
        "cell_size_m": CELL_M,
        "scope": {"max_sheets": args.max_sheets, "per_sheet_positives": args.per_sheet_positives, "per_sheet_negatives": args.per_sheet_negatives},
    }
    try:
        if args.selection.exists():
            candidates, stored = read_selection(args.selection)
            compared = ("negative_rule", "footprint_area_m2_range", "seed", "cell_size_m", "scope")
            if {key: stored.get(key) for key in compared} != {key: meta[key] for key in compared}:
                raise DatasetError(f"{args.selection} was built with different selection rules; pass a new --selection path.")
            logger.info("Reusing selection %s with %d candidates.", args.selection, len(candidates))
        else:
            candidates = select(args.registry, args.buildings, args)
            write_selection(args.selection, candidates, meta)
            logger.info("Wrote %s with %d candidates.", args.selection, len(candidates))
        if args.select_only:
            counts = Counter(candidate.dataset_class for candidate in candidates)
            print(json.dumps({"status": "selected", "selection": str(args.selection), "candidates": dict(counts), "cells": len({tuple(candidate.cell) for candidate in candidates})}))
            return 0
        counts = build(candidates, args, meta)
        print(json.dumps({"status": "ok", "output": str(args.output), "counts": dict(counts)}, ensure_ascii=False))
        return 0
    except (DatasetError, CropError) as error:
        print(json.dumps({"status": getattr(error, "status", "dataset_error"), "detail": str(error)}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled", "detail": "Interrupted; rerun to resume from the manifest."}), file=sys.stderr)
        return 130
