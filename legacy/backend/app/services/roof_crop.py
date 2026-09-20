import argparse
import json
import logging
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import rasterio
from pyproj import CRS
from rasterio.enums import ColorInterp, Resampling
from rasterio.errors import RasterioError
from rasterio.io import MemoryFile
from rasterio.transform import Affine, from_origin
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds
from shapely.geometry import Polygon, box

from app.providers.roof_imagery import INDEX_URL, CachedRaster, CropError, OrthoSource, discover_sources, download_source
from app.services.geo import to_2180, to_4326, validate_polygon

SIZE_PX = 47
RESOLUTION_M = 0.25
SIDE_M = SIZE_PX * RESOLUTION_M
MAX_INPUT_BYTES = 2 * 1024 * 1024
DEFAULT_DOWNLOAD_BYTES = 1536 * 1024 * 1024
DEFAULT_SELECTION = "smallest RGB pixel, then newest acquisition date; optional year filter"


@dataclass(frozen=True)
class RoofWindow:
    center_2180: tuple[float, float]
    center_4326: tuple[float, float]
    bounds: tuple[float, float, float, float]
    transform: Affine
    roof: Polygon


def build_window(payload: Any) -> RoofWindow:
    if not isinstance(payload, dict):
        raise CropError("invalid_input", "Expected a GeoJSON Polygon or Feature containing one Polygon.")
    geometry = payload.get("geometry") if payload.get("type") == "Feature" else payload
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise CropError("invalid_input", "Expected one Polygon; MultiPolygon and FeatureCollection are not selected implicitly.")
    if "crs" in payload or "crs" in geometry:
        raise CropError("invalid_input", "Input CRS must be WGS84 GeoJSON without a legacy crs member.")
    rings = geometry.get("coordinates")
    if not isinstance(rings, (list, tuple)) or not rings:
        raise CropError("invalid_input", "Polygon coordinates must contain closed rings.")
    west, south, east, north = CRS.from_epsg(2180).area_of_use.bounds
    for ring in rings:
        if not isinstance(ring, (list, tuple)) or len(ring) < 4 or ring[0] != ring[-1]:
            raise CropError("invalid_input", "Each polygon ring must have at least four positions and be explicitly closed.")
        for position in ring:
            if not isinstance(position, (list, tuple)) or len(position) != 2 or any(type(value) not in (float, int) or (isinstance(value, float) and not math.isfinite(value)) for value in position):
                raise CropError("invalid_input", "Positions must contain two finite numbers: [longitude, latitude].")
            if not (west <= position[0] <= east and south <= position[1] <= north):
                raise CropError("invalid_input", "Coordinates are outside the supported Poland extent; check longitude/latitude order.")
    try:
        polygon = to_2180(validate_polygon(geometry))
    except (ValueError, TypeError) as error:
        raise CropError("invalid_input", "Polygon must have valid topology and nonzero area.") from error
    if not polygon.is_valid or polygon.area <= 0:
        raise CropError("invalid_input", "Projected polygon must have valid topology and nonzero area.")
    center = polygon.centroid
    if not polygon.contains(center):
        raise CropError("needs_review", "Surface centroid lies outside the roof or inside a courtyard; no substitute center was used.")
    half = SIDE_M / 2
    bounds = (center.x - half, center.y - half, center.x + half, center.y + half)
    geographic_center = to_4326(center)
    return RoofWindow((center.x, center.y), (geographic_center.x, geographic_center.y), bounds, from_origin(bounds[0], bounds[3], RESOLUTION_M, RESOLUTION_M), polygon)


def crop_raster(path: Path, window: RoofWindow, source: OrthoSource) -> tuple[bytes, dict[str, Any]]:
    try:
        with rasterio.open(path, OVERVIEW_LEVEL="NONE") as dataset:
            if dataset.crs is None or not dataset.crs.is_projected or dataset.crs.linear_units not in ("metre", "meter"):
                raise CropError("invalid_raster", "Original raster needs a projected, metre-based CRS.")
            resolution = dataset.res
            if max(resolution) > RESOLUTION_M + 1e-8:
                raise CropError("insufficient_resolution", "Actual native raster resolution is coarser than 0.25 m/pixel.")
            if not all(math.isclose(value, source.resolution_m, rel_tol=1e-4, abs_tol=1e-8) for value in resolution):
                raise CropError("invalid_metadata", "Native raster resolution differs from the selected index record.")
            if not 0.01 <= min(resolution) or dataset.transform.b != 0 or dataset.transform.d != 0 or dataset.transform.a <= 0 or dataset.transform.e >= 0:
                raise CropError("invalid_raster", "Unsupported raster grid; expected a north-up orthophoto with pixels of at least 1 cm.")
            rgb = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
            if all(color in dataset.colorinterp for color in rgb):
                indexes = [dataset.colorinterp.index(color) + 1 for color in rgb]
            elif dataset.count == 3 and all(color == ColorInterp.undefined for color in dataset.colorinterp):
                indexes = [1, 2, 3]
            else:
                raise CropError("invalid_raster", "Original must contain RGB bands, not a palette or infrared image.")
            if any(dataset.dtypes[index - 1] != "uint8" for index in indexes):
                raise CropError("invalid_raster", "Expected 8-bit RGB; no automatic radiometric scaling is applied.")
            bounds = transform_bounds("EPSG:2180", dataset.crs, *window.bounds, densify_pts=21)
            if not box(*dataset.bounds).buffer(1e-7).covers(box(*bounds)):
                raise CropError("no_coverage", "Selected original does not cover the complete crop; cross-sheet mosaics are not generated. Try another --year.")
            fractional = from_bounds(*bounds, transform=dataset.transform)
            left, top = max(0, math.floor(fractional.col_off)), max(0, math.floor(fractional.row_off))
            right = min(dataset.width, math.ceil(fractional.col_off + fractional.width))
            bottom = min(dataset.height, math.ceil(fractional.row_off + fractional.height))
            native_window = Window(left, top, right - left, bottom - top)
            if not dataset.read_masks(indexes, window=native_window).all():
                raise CropError("no_coverage", "NoData or transparent pixels intersect the source crop window.")
            pixels = dataset.read(indexes, window=native_window)
            output = np.zeros((3, SIZE_PX, SIZE_PX), dtype="uint8")
            for band in range(3):
                reproject(pixels[band], output[band], src_transform=dataset.window_transform(native_window), src_crs=dataset.crs, dst_transform=window.transform, dst_crs="EPSG:2180", resampling=Resampling.average)
            metadata = {"crs": dataset.crs.to_string(), "native_resolution_m": list(resolution), "bands": indexes, "dtype": "uint8", "resampling": "area_average", "overviews_used": False}
        with MemoryFile() as memory:
            with memory.open(driver="PNG", width=SIZE_PX, height=SIZE_PX, count=3, dtype="uint8", transform=window.transform) as image:
                image.write(output)
            png = memory.read()
    except RasterioError as error:
        raise CropError("invalid_raster", "Could not read the original GeoTIFF or generate the PNG.") from error
    return png, metadata


def crop_metadata(window: RoofWindow, source: OrthoSource, cached: CachedRaster, raster_metadata: dict[str, Any], year: int | None, selection: str = DEFAULT_SELECTION) -> dict[str, Any]:
    return {
        "status": "ok",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "paper_doi": "10.1016/j.buildenv.2022.109092",
        "center": {"method": "projected_surface_centroid", "epsg2180_xy": list(window.center_2180), "wgs84_lon_lat": list(window.center_4326)},
        "output": {"format": "PNG", "channels": "RGB", "size_px": [SIZE_PX, SIZE_PX], "resolution_m": RESOLUTION_M, "extent_m": [SIDE_M, SIDE_M], "crs": "EPSG:2180", "bbox_xy": list(window.bounds), "affine": list(window.transform)[:6], "roof_overlap_fraction": window.roof.intersection(box(*window.bounds)).area / SIDE_M**2, "standardization": None},
        "source": {"provider": "GUGiK", "index_url": INDEX_URL, "url": source.url, "sheet": source.sheet, "acquisition_date": source.acquisition_date.isoformat(), "index_resolution_m": source.resolution_m, "sha256": cached.sha256, "size_bytes": cached.size_bytes, "cache_path": str(cached.path.resolve()), "selection": selection, "requested_year": year},
        "raster": raster_metadata,
        "attribution": "Orthophotomap: GUGiK / Geoportal.gov.pl",
        "warnings": [
            "The center is an automatic polygon centroid, not a visually selected roof center as discussed in the paper.",
            "Verify roof alignment against the selected acquisition; best-resolution imagery is not necessarily the newest imagery.",
            "The fixed square retains surroundings. Spatial dimensions match the paper; resampling and source imagery are not an exact reproduction of its training data.",
        ],
    }


def run_crop(payload: dict[str, Any], client: httpx.Client, cache_dir: Path, year: int | None = None, max_download_bytes: int = DEFAULT_DOWNLOAD_BYTES) -> tuple[bytes, dict[str, Any]]:
    window = build_window(payload)
    source = discover_sources(client, *window.center_4326, year=year)[0]
    logger = logging.getLogger("roofer.crop")
    logger.info("Selected RGB sheet %s, acquired %s, native pixel %.3f m. Checking cache or downloading the original (limit %.0f MiB).", source.sheet, source.acquisition_date, source.resolution_m, max_download_bytes / 1024**2)
    cached = download_source(client, source, cache_dir, max_download_bytes)
    logger.info("Original verified (%.1f MiB). Generating the 47x47 crop.", cached.size_bytes / 1024**2)
    png, raster_metadata = crop_raster(cached.path, window, source)
    return png, crop_metadata(window, source, cached, raster_metadata, year)


def output_paths(prefix: Path) -> tuple[Path, Path]:
    return Path(f"{prefix}.png"), Path(f"{prefix}.json")


def ensure_new_outputs(prefix: Path) -> None:
    if any(path.exists() or path.is_symlink() for path in output_paths(prefix)):
        raise CropError("output_exists", "Output PNG or JSON already exists; choose a new --output prefix.")


def export_crop(prefix: Path, png: bytes, metadata: dict[str, Any]) -> None:
    ensure_new_outputs(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for path, content in zip(output_paths(prefix), (png, (json.dumps(metadata, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8"))):
            with path.open("xb") as stream:
                created.append(path)
                stream.write(content)
    except OSError as error:
        for path in created:
            path.unlink(missing_ok=True)
        if isinstance(error, FileExistsError):
            raise CropError("output_exists", "Output appeared during export; existing files were not overwritten.") from error
        raise


def default_cache_dir() -> Path:
    root = os.getenv("LOCALAPPDATA") or os.getenv("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(root) / "Roofer" / "orthophotos"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crop a roof GeoJSON to RGB 47x47 pixels at 0.25 m/px (11.75x11.75 m) using an original GUGiK GeoTIFF. Geometry is in WGS84 [longitude, latitude], within Poland.")
    parser.add_argument("--input", required=True, help="GeoJSON Polygon/Feature file, or - for stdin")
    parser.add_argument("--output", required=True, type=Path, help="New output prefix; writes PREFIX.png and PREFIX.json without overwriting")
    parser.add_argument("--cache-dir", type=Path, default=default_cache_dir(), help="Original GeoTIFF cache (default: OS user cache/Roofer/orthophotos)")
    parser.add_argument("--year", type=int, help="Restrict imagery acquisition year, e.g. to match the image used to draw the roof")
    parser.add_argument("--max-download-mb", type=float, default=1536, help="Maximum new original download in MiB (default: 1536); verified cache is reused without downloading")
    parser.add_argument("--timeout", type=float, default=60, help="Network inactivity timeout in seconds (default: 60)")
    args = parser.parse_args(argv)
    if not math.isfinite(args.max_download_mb * 1024**2) or args.max_download_mb <= 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("Download limit and timeout must be positive finite numbers.")
    if args.year is not None and not 1900 <= args.year <= datetime.now(timezone.utc).year:
        parser.error("Year must be between 1900 and the current year.")
    try:
        ensure_new_outputs(args.output)
        if args.input == "-":
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        else:
            with Path(args.input).open("rb") as stream:
                raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise CropError("invalid_input", "GeoJSON exceeds the 2 MiB input limit.")
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError, RecursionError) as error:
            raise CropError("invalid_input", "Input must be valid UTF-8 GeoJSON.") from error
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        with httpx.Client(timeout=args.timeout, follow_redirects=False, headers={"User-Agent": "Roofer-roof-crop/1.0"}) as client:
            png, metadata = run_crop(payload, client, args.cache_dir, year=args.year, max_download_bytes=int(args.max_download_mb * 1024**2))
        export_crop(args.output, png, metadata)
        print(json.dumps({"status": "ok", "png": str(output_paths(args.output)[0]), "metadata": str(output_paths(args.output)[1]), "source_resolution_m": metadata["source"]["index_resolution_m"], "acquisition_date": metadata["source"]["acquisition_date"]}))
        return 0
    except CropError as error:
        print(json.dumps({"status": error.status, "detail": str(error)}), file=sys.stderr)
        return 2
    except OSError as error:
        print(json.dumps({"status": "io_error", "detail": str(error)}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled", "detail": "Crop cancelled; incomplete downloads are not reused."}), file=sys.stderr)
        return 130
