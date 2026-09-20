#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import sqlite3
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

try:
    import numpy as np
    import requests
    from PIL import Image, ImageDraw, ImageFilter
except ImportError as error:
    raise SystemExit(
        "Brak zależności. Uruchom: python3 -m pip install -r requirements-dataset.txt"
    ) from error

TILE_SIZE = 256
REFERENCE_LATITUDE = 52.2
METERS_PER_DEGREE = 111_320.0
GOOGLE_TILE_URL = "https://mt1.google.com/vt"
THREAD_LOCAL = threading.local()
QUALITY_FIELDS = ("roof_fraction", "green_fraction", "roof_green_fraction", "sharpness", "contrast", "edge_density", "region_source")
QUALITY_DEFAULTS = {
    "min_sharpness": 40.0, "min_contrast": 8.0, "min_edge_density": 0.02,
    "max_green_fraction": 0.65, "max_roof_green_fraction": 0.35, "min_roof_fraction": 0.15,
}
QUALITY_OPTIONS = tuple(QUALITY_DEFAULTS)


@dataclass(slots=True)
class Candidate:
    source_id: str
    longitude: float
    latitude: float
    area_m2: float
    width_px: float
    height_px: float
    metric_x: float
    metric_y: float
    nearby_buildings: int = 0
    polygon: list = field(default_factory=list)
    crop_polygon: list = field(default_factory=list)
    center_method: str = "centroid"
    quality: dict = field(default_factory=dict)


class QualityRejected(ValueError):
    def __init__(self, reasons: list[str], metrics: dict, image: Image.Image):
        super().__init__(", ".join(reasons))
        self.reasons = reasons
        self.metrics = metrics
        self.image = image


class Reservoir:
    def __init__(self, capacity: int, rng: random.Random):
        self.capacity = capacity
        self.rng = rng
        self.items: list[Candidate] = []
        self.seen = 0

    def add(self, item: Candidate) -> None:
        self.seen += 1
        if len(self.items) < self.capacity:
            self.items.append(item)
            return
        index = self.rng.randrange(self.seen)
        if index < self.capacity:
            self.items[index] = item


def parse_args() -> argparse.Namespace:
    data_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Buduje dataset zdjęć dachów azbestowych i nieazbestowych z kafelków Google."
    )
    parser.add_argument(
        "--buildings-geojson",
        type=Path,
        default=data_dir / "budynki-osm-mazowieckie.geojson",
    )
    parser.add_argument(
        "--asbestos-geojson",
        type=Path,
        default=data_dir / "geoazbest-mazowieckie.geojson",
    )
    parser.add_argument("--output-dir", type=Path, default=data_dir / "roof_dataset")
    parser.add_argument("--asbestos-count", type=int, default=500)
    parser.add_argument("--non-asbestos-count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=2022)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--zoom", type=int, default=20)
    parser.add_argument("--crop-size", type=int, default=128)
    parser.add_argument("--min-area-m2", type=float, default=25.0)
    parser.add_argument("--min-bbox-side-px", type=float, default=20.0)
    parser.add_argument("--village-radius-m", type=float, default=300.0)
    parser.add_argument("--min-nearby-buildings", type=int, default=12)
    parser.add_argument("--density-cell-m", type=float, default=75.0)
    parser.add_argument("--asbestos-exclusion-buffer-m", type=float, default=5.0)
    parser.add_argument("--min-center-distance-m", type=float, default=8.0)
    parser.add_argument("--candidate-pool-multiplier", type=int, default=100)
    parser.add_argument("--tile-cache", type=Path)
    parser.add_argument("--request-timeout", type=float, default=20.0)
    parser.add_argument("--request-attempts", type=int, default=4)
    parser.add_argument("--min-sharpness", type=float, default=QUALITY_DEFAULTS["min_sharpness"], help="Minimalna wariancja Laplasjanu w obszarze dachu (proxy ostrości)")
    parser.add_argument("--min-contrast", type=float, default=QUALITY_DEFAULTS["min_contrast"], help="Minimalne odchylenie jasności w obszarze dachu")
    parser.add_argument("--min-edge-density", type=float, default=QUALITY_DEFAULTS["min_edge_density"])
    parser.add_argument("--max-green-fraction", type=float, default=QUALITY_DEFAULTS["max_green_fraction"])
    parser.add_argument("--max-roof-green-fraction", type=float, default=QUALITY_DEFAULTS["max_roof_green_fraction"])
    parser.add_argument("--min-roof-fraction", type=float, default=QUALITY_DEFAULTS["min_roof_fraction"], help="Minimalny udział obrysu budynku w kadrze; duże dachy mogą być ucięte")
    parser.add_argument("--audit-dataset", type=Path, help="Oceń istniejący dataset bez zmiany zdjęć i bez pobierania kafelków; zapisz raport w --output-dir")
    args = parser.parse_args()

    positive_names = (
        "asbestos_count",
        "non_asbestos_count",
        "workers",
        "crop_size",
        "min_nearby_buildings",
        "candidate_pool_multiplier",
        "request_attempts",
    )
    for name in positive_names:
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} musi być większe od zera")
    if args.zoom != 20:
        parser.error("Ten dataset ma używać zoomu 20")
    if args.crop_size != 128:
        parser.error("Ten dataset ma używać wycinków 128×128 px")
    if args.min_area_m2 <= 0 or args.min_bbox_side_px <= 0:
        parser.error("Minimalny rozmiar dachu musi być większy od zera")
    if args.village_radius_m <= 0 or args.density_cell_m <= 0:
        parser.error("Promień wioski i komórka gęstości muszą być większe od zera")
    for name in QUALITY_OPTIONS:
        value = getattr(args, name)
        if not math.isfinite(value) or value < 0 or (name.endswith(("fraction", "density")) and value > 1):
            parser.error(f"Nieprawidłowy --{name.replace('_', '-')}")
    return args


def iter_geojson_features(path: Path):
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            value = line.strip()
            if not value.startswith('{"type":"Feature"'):
                continue
            if value.endswith(","):
                value = value[:-1]
            try:
                yield json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError(f"Nieprawidłowy GeoJSON: {path}:{line_number}") from error


def geometry_polygons(geometry: dict | None) -> list:
    if not geometry:
        return []
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon" and coordinates:
        return [coordinates]
    if geometry_type == "MultiPolygon" and coordinates:
        return coordinates
    return []


def valid_ring(ring) -> list[tuple[float, float]]:
    points = []
    for position in ring:
        if not isinstance(position, list) or len(position) < 2:
            continue
        longitude, latitude = position[:2]
        if not isinstance(longitude, (int, float)) or not isinstance(latitude, (int, float)):
            continue
        if -180 <= longitude <= 180 and -85 <= latitude <= 85:
            points.append((float(longitude), float(latitude)))
    return points


def ring_area_centroid(ring) -> tuple[float, float, float] | None:
    points = valid_ring(ring)
    if len(points) < 3:
        return None
    origin_longitude, origin_latitude = points[0]
    local_points = [
        (longitude - origin_longitude, latitude - origin_latitude)
        for longitude, latitude in points
    ]
    cross_sum = 0.0
    longitude_sum = 0.0
    latitude_sum = 0.0
    for (x1, y1), (x2, y2) in zip(local_points, local_points[1:] + local_points[:1]):
        cross = x1 * y2 - x2 * y1
        cross_sum += cross
        longitude_sum += (x1 + x2) * cross
        latitude_sum += (y1 + y2) * cross
    if abs(cross_sum) < 1e-16:
        return None
    return (
        abs(cross_sum) / 2,
        origin_longitude + longitude_sum / (3 * cross_sum),
        origin_latitude + latitude_sum / (3 * cross_sum),
    )


def geometry_centroid(polygons: list) -> tuple[float, float] | None:
    weighted_longitude = 0.0
    weighted_latitude = 0.0
    total_weight = 0.0
    fallback_points = []
    for polygon in polygons:
        polygon_weight = 0.0
        polygon_longitude = 0.0
        polygon_latitude = 0.0
        for ring_index, ring in enumerate(polygon):
            points = valid_ring(ring)
            fallback_points.extend(points)
            stats = ring_area_centroid(ring)
            if not stats:
                continue
            area, longitude, latitude = stats
            weight = area if ring_index == 0 else -area
            polygon_weight += weight
            polygon_longitude += longitude * weight
            polygon_latitude += latitude * weight
        if polygon_weight > 0:
            weighted_longitude += polygon_longitude
            weighted_latitude += polygon_latitude
            total_weight += polygon_weight
    if total_weight > 0:
        return weighted_longitude / total_weight, weighted_latitude / total_weight
    if fallback_points:
        return (
            (min(point[0] for point in fallback_points) + max(point[0] for point in fallback_points)) / 2,
            (min(point[1] for point in fallback_points) + max(point[1] for point in fallback_points)) / 2,
        )
    return None


def ring_area_m2(ring, center_longitude: float, center_latitude: float) -> float:
    points = valid_ring(ring)
    if len(points) < 3:
        return 0.0
    longitude_scale = METERS_PER_DEGREE * math.cos(math.radians(center_latitude))
    transformed = [
        ((longitude - center_longitude) * longitude_scale, (latitude - center_latitude) * METERS_PER_DEGREE)
        for longitude, latitude in points
    ]
    cross_sum = sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(transformed, transformed[1:] + transformed[:1])
    )
    return abs(cross_sum) / 2


def geometry_area_m2(polygons: list, center_longitude: float, center_latitude: float) -> float:
    area = 0.0
    for polygon in polygons:
        if not polygon:
            continue
        area += ring_area_m2(polygon[0], center_longitude, center_latitude)
        area -= sum(
            ring_area_m2(ring, center_longitude, center_latitude) for ring in polygon[1:]
        )
    return max(area, 0.0)


def world_pixel(longitude: float, latitude: float, zoom: int) -> tuple[float, float]:
    scale = TILE_SIZE * (2**zoom)
    latitude = min(max(latitude, -85.05112878), 85.05112878)
    x = (longitude + 180.0) / 360.0 * scale
    y = (
        1.0
        - math.asinh(math.tan(math.radians(latitude))) / math.pi
    ) / 2.0 * scale
    return x, y


def metric_point(longitude: float, latitude: float) -> tuple[float, float]:
    return (
        longitude * METERS_PER_DEGREE * math.cos(math.radians(REFERENCE_LATITUDE)),
        latitude * METERS_PER_DEGREE,
    )


def geometry_bbox(polygons: list) -> tuple[float, float, float, float] | None:
    points = [point for polygon in polygons for ring in polygon for point in valid_ring(ring)]
    if not points:
        return None
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return min(longitudes), max(longitudes), min(latitudes), max(latitudes)


def point_in_ring(point: tuple[float, float], ring: list) -> bool:
    x, y = point
    points = valid_ring(ring)
    inside = False
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def point_in_polygon(point: tuple[float, float], polygon: list) -> bool:
    return bool(polygon) and point_in_ring(point, polygon[0]) and not any(point_in_ring(point, hole) for hole in polygon[1:])


def roof_center(polygons: list) -> tuple[tuple[float, float], list, str] | None:
    candidates = []
    for polygon in polygons:
        stats = [ring_area_centroid(ring) for ring in polygon]
        if not stats or stats[0] is None:
            continue
        area = stats[0][0] - sum(item[0] for item in stats[1:] if item)
        if area > 0:
            candidates.append((area, polygon))
    if not candidates:
        return None
    _, polygon = max(candidates, key=lambda item: item[0])
    center = geometry_centroid([polygon])
    if center and point_in_polygon(center, polygon):
        return center, polygon, "centroid"
    rings = [valid_ring(ring) for ring in polygon]
    edges = [(first, second) for ring in rings for first, second in zip(ring, ring[1:] + ring[:1])]
    levels = sorted({point[1] for ring in rings for point in ring})
    best = None
    best_clearance = -1.0
    for lower, upper in zip(levels, levels[1:]):
        y = (lower + upper) / 2
        crossings = sorted(x1 + (y - y1) * (x2 - x1) / (y2 - y1) for (x1, y1), (x2, y2) in edges if (y1 > y) != (y2 > y))
        for left, right in zip(crossings[::2], crossings[1::2]):
            point = ((left + right) / 2, y)
            if not point_in_polygon(point, polygon):
                continue
            scale = math.cos(math.radians(y))
            clearance = math.inf
            for (x1, y1), (x2, y2) in edges:
                dx, dy = (x2 - x1) * scale, y2 - y1
                px, py = (point[0] - x1) * scale, y - y1
                length_squared = dx * dx + dy * dy
                fraction = min(1, max(0, (px * dx + py * dy) / length_squared)) if length_squared else 0
                clearance = min(clearance, (px - fraction * dx) ** 2 + (py - fraction * dy) ** 2)
            if clearance > best_clearance:
                best, best_clearance = point, clearance
    return (best, polygon, "interior_point") if best else None


def candidate_from_feature(feature: dict, args: argparse.Namespace) -> Candidate | None:
    selected = roof_center(geometry_polygons(feature.get("geometry")))
    if not selected:
        return None
    (longitude, latitude), polygon, center_method = selected
    polygons = [polygon]
    area_m2 = geometry_area_m2(polygons, longitude, latitude)
    pixel_points = [
        world_pixel(point[0], point[1], args.zoom)
        for polygon in polygons
        for ring in polygon
        for point in valid_ring(ring)
    ]
    if not pixel_points:
        return None
    width_px = max(point[0] for point in pixel_points) - min(point[0] for point in pixel_points)
    height_px = max(point[1] for point in pixel_points) - min(point[1] for point in pixel_points)
    if area_m2 < args.min_area_m2 or min(width_px, height_px) < args.min_bbox_side_px:
        return None
    source_id = str(
        feature.get("id")
        or feature.get("properties", {}).get("osm_id")
        or feature.get("properties", {}).get("fid")
        or "unknown"
    )
    metric_x, metric_y = metric_point(longitude, latitude)
    return Candidate(
        source_id=source_id,
        longitude=longitude,
        latitude=latitude,
        area_m2=area_m2,
        width_px=width_px,
        height_px=height_px,
        metric_x=metric_x,
        metric_y=metric_y,
        polygon=polygon,
        center_method=center_method,
    )


def create_asbestos_index(
    connection: sqlite3.Connection,
    path: Path,
    reservoir: Reservoir,
    args: argparse.Namespace,
) -> dict[str, int]:
    connection.execute(
        "CREATE VIRTUAL TABLE asbestos_bounds USING rtree(id, min_lon, max_lon, min_lat, max_lat)"
    )
    batch = []
    indexed = 0
    eligible = 0
    duplicate_centers = 0
    seen_centers = set()
    for total, feature in enumerate(iter_geojson_features(path), start=1):
        polygons = geometry_polygons(feature.get("geometry"))
        bbox = geometry_bbox(polygons)
        if bbox:
            min_lon, max_lon, min_lat, max_lat = bbox
            latitude = (min_lat + max_lat) / 2
            latitude_padding = args.asbestos_exclusion_buffer_m / METERS_PER_DEGREE
            longitude_padding = latitude_padding / max(math.cos(math.radians(latitude)), 0.1)
            indexed += 1
            batch.append(
                (
                    indexed,
                    min_lon - longitude_padding,
                    max_lon + longitude_padding,
                    min_lat - latitude_padding,
                    max_lat + latitude_padding,
                )
            )
            if len(batch) >= 5000:
                connection.executemany(
                    "INSERT INTO asbestos_bounds VALUES (?, ?, ?, ?, ?)", batch
                )
                batch.clear()
        candidate = candidate_from_feature(feature, args)
        if candidate:
            center_key = tuple(round(value) for value in world_pixel(
                candidate.longitude, candidate.latitude, args.zoom
            ))
            if center_key in seen_centers:
                duplicate_centers += 1
            else:
                seen_centers.add(center_key)
                eligible += 1
                reservoir.add(candidate)
        if total % 50_000 == 0:
            print(f"GeoAzbest: odczytano {total:,} obiektów", flush=True)
    if batch:
        connection.executemany("INSERT INTO asbestos_bounds VALUES (?, ?, ?, ?, ?)", batch)
    connection.commit()
    return {
        "total": total if "total" in locals() else 0,
        "indexed": indexed,
        "eligible_size": eligible,
        "duplicate_centers": duplicate_centers,
    }


def overlaps_asbestos(
    connection: sqlite3.Connection, bbox: tuple[float, float, float, float]
) -> bool:
    min_lon, max_lon, min_lat, max_lat = bbox
    match = connection.execute(
        """
        SELECT 1 FROM asbestos_bounds
        WHERE min_lon <= ? AND max_lon >= ? AND min_lat <= ? AND max_lat >= ?
        LIMIT 1
        """,
        (max_lon, min_lon, max_lat, min_lat),
    ).fetchone()
    return match is not None


def scan_osm_buildings(
    connection: sqlite3.Connection,
    path: Path,
    reservoir: Reservoir,
    args: argparse.Namespace,
) -> tuple[Counter, dict[str, int]]:
    density = Counter()
    eligible = 0
    excluded_asbestos = 0
    for total, feature in enumerate(iter_geojson_features(path), start=1):
        polygons = geometry_polygons(feature.get("geometry"))
        center = geometry_centroid(polygons)
        if center:
            metric_x, metric_y = metric_point(*center)
            density[
                (
                    math.floor(metric_x / args.density_cell_m),
                    math.floor(metric_y / args.density_cell_m),
                )
            ] += 1
        candidate = candidate_from_feature(feature, args)
        if candidate:
            bbox = geometry_bbox(polygons)
            if bbox and overlaps_asbestos(connection, bbox):
                excluded_asbestos += 1
            elif bbox:
                eligible += 1
                reservoir.add(candidate)
        if total % 100_000 == 0:
            print(f"OSM: odczytano {total:,} budynków", flush=True)
    return density, {
        "total": total if "total" in locals() else 0,
        "eligible_size_and_non_asbestos": eligible,
        "excluded_by_geoazbest": excluded_asbestos,
        "density_cells": len(density),
    }


def nearby_building_count(candidate: Candidate, density: Counter, args: argparse.Namespace) -> int:
    cell = args.density_cell_m
    radius = args.village_radius_m
    min_x = math.floor((candidate.metric_x - radius) / cell)
    max_x = math.floor((candidate.metric_x + radius) / cell)
    min_y = math.floor((candidate.metric_y - radius) / cell)
    max_y = math.floor((candidate.metric_y + radius) / cell)
    count = 0
    for cell_x in range(min_x, max_x + 1):
        left = cell_x * cell
        right = left + cell
        closest_x = min(max(candidate.metric_x, left), right)
        for cell_y in range(min_y, max_y + 1):
            bottom = cell_y * cell
            top = bottom + cell
            closest_y = min(max(candidate.metric_y, bottom), top)
            if math.hypot(candidate.metric_x - closest_x, candidate.metric_y - closest_y) <= radius:
                count += density.get((cell_x, cell_y), 0)
    return count


def village_candidates(
    candidates: list[Candidate], density: Counter, args: argparse.Namespace
) -> list[Candidate]:
    accepted = []
    for candidate in candidates:
        candidate.nearby_buildings = nearby_building_count(candidate, density, args)
        if candidate.nearby_buildings >= args.min_nearby_buildings:
            accepted.append(candidate)
    return accepted


def spaced_candidates(
    candidates: list[Candidate], minimum_distance: float, rng: random.Random
) -> list[Candidate]:
    rng.shuffle(candidates)
    if minimum_distance <= 0:
        return candidates
    cells: dict[tuple[int, int], list[Candidate]] = {}
    accepted = []
    for candidate in candidates:
        key = (
            math.floor(candidate.metric_x / minimum_distance),
            math.floor(candidate.metric_y / minimum_distance),
        )
        too_close = False
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                for previous in cells.get((key[0] + offset_x, key[1] + offset_y), []):
                    if math.hypot(
                        candidate.metric_x - previous.metric_x,
                        candidate.metric_y - previous.metric_y,
                    ) < minimum_distance:
                        too_close = True
                        break
                if too_close:
                    break
            if too_close:
                break
        if not too_close:
            cells.setdefault(key, []).append(candidate)
            accepted.append(candidate)
    return accepted


def request_session() -> requests.Session:
    if not hasattr(THREAD_LOCAL, "session"):
        session = requests.Session()
        session.headers.update({"User-Agent": "RooferDatasetBuilder/1.0"})
        THREAD_LOCAL.session = session
    return THREAD_LOCAL.session


def load_tile(
    tile_x: int,
    tile_y: int,
    zoom: int,
    cache_dir: Path,
    timeout: float,
    attempts: int,
) -> Image.Image:
    tile_count = 2**zoom
    tile_x %= tile_count
    if not 0 <= tile_y < tile_count:
        raise ValueError(f"Nieprawidłowy numer kafelka y={tile_y}")
    cache_path = cache_dir / str(zoom) / str(tile_x) / f"{tile_y}.tile"
    if cache_path.is_file():
        try:
            with Image.open(cache_path) as cached:
                if cached.size == (TILE_SIZE, TILE_SIZE):
                    return cached.convert("RGB")
        except OSError:
            pass
    last_error = None
    for attempt in range(attempts):
        try:
            response = request_session().get(
                GOOGLE_TILE_URL,
                params={"lyrs": "s", "x": tile_x, "y": tile_y, "z": zoom},
                timeout=timeout,
            )
            response.raise_for_status()
            with Image.open(BytesIO(response.content)) as downloaded:
                if downloaded.size != (TILE_SIZE, TILE_SIZE):
                    raise ValueError(f"Kafelek ma rozmiar {downloaded.size}")
                tile = downloaded.convert("RGB")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=cache_path.parent, delete=False) as temporary:
                temporary.write(response.content)
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, cache_path)
            return tile
        except (OSError, requests.RequestException, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.75 * (2**attempt))
    raise RuntimeError(f"Nie udało się pobrać kafelka {zoom}/{tile_x}/{tile_y}: {last_error}")


def polygon_mask(polygon: list, size: tuple[int, int]) -> Image.Image:
    mask = Image.new("L", size)
    draw = ImageDraw.Draw(mask)
    for index, ring in enumerate(polygon):
        if len(ring) >= 3:
            draw.polygon([tuple(point) for point in ring], fill=255 if index == 0 else 0)
    return mask


def assess_image_quality(image: Image.Image, roof_mask: Image.Image | None, args: argparse.Namespace) -> tuple[dict, list[str]]:
    if image.size != (128, 128):
        raise ValueError(f"Kontrola jakości wymaga 128×128, otrzymano {image.size}")
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    red, green, blue = pixels.transpose(2, 0, 1)
    vegetation = (green > 35) & (green > red * 1.07) & (green > blue * 1.04) & ((2 * green - red - blue) > 15)
    has_footprint = roof_mask is not None
    if roof_mask is None:
        roof_mask = Image.new("L", image.size)
        ImageDraw.Draw(roof_mask).rectangle((32, 32, 95, 95), fill=255)
    if roof_mask.size != image.size:
        raise ValueError("Maska obrysu ma inny rozmiar niż zdjęcie")
    region = np.asarray(roof_mask) > 0
    interior = np.asarray(roof_mask.filter(ImageFilter.MinFilter(5))) > 0
    usable = interior[1:-1, 1:-1]
    laplacian = gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:] - 4 * gray[1:-1, 1:-1]
    gradient = np.hypot(gray[1:-1, 2:] - gray[1:-1, :-2], gray[2:, 1:-1] - gray[:-2, 1:-1]) / 2
    metrics = {
        "roof_fraction": float(region.mean()) if has_footprint else None,
        "green_fraction": float(vegetation.mean()),
        "roof_green_fraction": float(vegetation[region].mean()) if region.any() else 0.0,
        "sharpness": float(laplacian[usable].var()) if usable.any() else 0.0,
        "contrast": float(gray[region].std()) if region.any() else 0.0,
        "edge_density": float((gradient[usable] >= 12).mean()) if usable.any() else 0.0,
        "region_source": "footprint" if has_footprint else "center_fallback",
    }
    checks = (
        (has_footprint and metrics["roof_fraction"] < args.min_roof_fraction, "insufficient_roof_coverage"),
        (metrics["green_fraction"] > args.max_green_fraction, "too_much_green"),
        (metrics["roof_green_fraction"] > args.max_roof_green_fraction, "green_over_roof"),
        (metrics["sharpness"] < args.min_sharpness, "low_sharpness"),
        (metrics["contrast"] < args.min_contrast, "low_contrast"),
        (metrics["edge_density"] < args.min_edge_density, "few_edges"),
    )
    return metrics, [reason for rejected, reason in checks if rejected]


def quality_settings(args: argparse.Namespace) -> dict:
    return {
        **{name: getattr(args, name) for name in QUALITY_OPTIONS},
        "sharpness_measure": "variance of 4-neighbor Laplacian inside eroded roof footprint",
        "edge_gradient_threshold": 12,
        "green_rule": "G>35, G>1.07R, G>1.04B, 2G-R-B>15",
        "heuristic_only": True,
        "limitations": "Does not prove roof presence or native imagery resolution. Stale footprints, non-green fields and green roofs need manual review.",
    }


def quality_preview(items: list[tuple[Image.Image, str]], path: Path) -> None:
    if not items:
        return
    columns = min(6, len(items))
    preview = Image.new("RGB", (columns * 128, math.ceil(len(items) / columns) * 160), "white")
    draw = ImageDraw.Draw(preview)
    for index, (image, label) in enumerate(items):
        x, y = (index % columns) * 128, (index // columns) * 160
        preview.paste(image, (x, y))
        draw.text((x + 2, y + 129), label[:21], fill="black")
        draw.text((x + 2, y + 143), label[21:42], fill="black")
    preview.save(path, quality=95)


def audit_existing_dataset(source: Path, output_dir: Path, args: argparse.Namespace) -> None:
    source = source.expanduser().resolve()
    with (source / "metadata.csv").open(encoding="utf-8", newline="") as stream:
        records = list(csv.DictReader(stream))
    assessed = []
    for record in records:
        path = (source / record["image_path"]).resolve()
        if not path.is_relative_to(source):
            raise ValueError(f"Ścieżka obrazu poza datasetem: {record['image_path']}")
        with Image.open(path) as image:
            footprint = json.loads(record["roof_polygon_px"]) if record.get("roof_polygon_px") else None
            mask = polygon_mask(footprint, image.size) if footprint else None
            metrics, reasons = assess_image_quality(image, mask, args)
        assessed.append({"image_path": record["image_path"], "class": record["class"], "status": "rejected" if reasons else "accepted", "reasons": "|".join(reasons), **metrics})
    fields = ["image_path", "class", "status", "reasons", *QUALITY_FIELDS]
    with (output_dir / "quality_audit.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(assessed)
    counts = Counter(row["status"] for row in assessed)
    summary = {
        "source": str(source), "total": len(assessed), "accepted": counts["accepted"], "rejected": counts["rejected"],
        "by_class": {name: dict(Counter(row["status"] for row in assessed if row["class"] == name)) for name in ("asbestos", "non_asbestos")},
        "reasons": dict(Counter(reason for row in assessed for reason in row["reasons"].split("|") if reason)),
        "region_sources": dict(Counter(row["region_source"] for row in assessed)),
        "settings": quality_settings(args),
        "quantiles": {name: dict(zip(("p10", "p50", "p90"), map(float, np.quantile([row[name] for row in assessed], [0.1, 0.5, 0.9])))) for name in ("sharpness", "contrast", "edge_density", "green_fraction", "roof_green_fraction")} if assessed else {},
    }
    (output_dir / "quality_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    for status in ("accepted", "rejected"):
        selected = [row for row in assessed if row["status"] == status]
        if status == "accepted":
            selected.sort(key=lambda row: row["sharpness"])
        items = []
        for row in selected[:36]:
            with Image.open(source / row["image_path"]) as image:
                items.append((image.convert("RGB"), f"{row['class']} L={row['sharpness']:.1f} {row['reasons']}"))
        quality_preview(items, output_dir / f"{status}_preview.jpg")
    print(json.dumps(summary, indent=2), flush=True)


def render_candidate(
    candidate: Candidate,
    class_name: str,
    destination: Path,
    cache_dir: Path,
    args: argparse.Namespace,
) -> tuple[Candidate, Path]:
    center_x, center_y = world_pixel(candidate.longitude, candidate.latitude, args.zoom)
    center_tile_x = math.floor(center_x / TILE_SIZE)
    center_tile_y = math.floor(center_y / TILE_SIZE)
    mosaic = Image.new("RGB", (TILE_SIZE * 3, TILE_SIZE * 3))
    for row, tile_y in enumerate(range(center_tile_y - 1, center_tile_y + 2)):
        for column, tile_x in enumerate(range(center_tile_x - 1, center_tile_x + 2)):
            tile = load_tile(
                tile_x,
                tile_y,
                args.zoom,
                cache_dir,
                args.request_timeout,
                args.request_attempts,
            )
            mosaic.paste(tile, (column * TILE_SIZE, row * TILE_SIZE))
    local_x = center_x - (center_tile_x - 1) * TILE_SIZE
    local_y = center_y - (center_tile_y - 1) * TILE_SIZE
    left = round(local_x - args.crop_size / 2)
    top = round(local_y - args.crop_size / 2)
    image = mosaic.crop((left, top, left + args.crop_size, top + args.crop_size)).convert("RGB")
    if image.size != (128, 128) or image.mode != "RGB":
        raise ValueError(f"Nieprawidłowy obraz wynikowy: {image.mode} {image.size}")
    origin_x = (center_tile_x - 1) * TILE_SIZE + left
    origin_y = (center_tile_y - 1) * TILE_SIZE + top
    candidate.crop_polygon = [
        [[x - origin_x, y - origin_y] for x, y in (world_pixel(*point, args.zoom) for point in valid_ring(ring))]
        for ring in candidate.polygon
    ]
    mask = polygon_mask(candidate.crop_polygon, image.size)
    candidate.quality, reasons = assess_image_quality(image, mask, args)
    if reasons:
        raise QualityRejected(reasons, candidate.quality, image)
    digest = hashlib.sha256(
        f"{class_name}|{candidate.source_id}|{candidate.longitude:.8f}|{candidate.latitude:.8f}".encode()
    ).hexdigest()[:16]
    path = destination / f"{class_name}_{digest}.png"
    image.save(path, format="PNG")
    return candidate, path


def download_class(
    candidates: list[Candidate],
    class_name: str,
    label: int,
    target: int,
    output_dir: Path,
    cache_dir: Path,
    args: argparse.Namespace,
) -> tuple[list[dict], list[str], list[dict]]:
    destination = output_dir / class_name
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    failures = []
    rejections = []
    rejected_preview = []
    cursor = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        while cursor < len(candidates) and len(records) < target:
            chunk = candidates[cursor : cursor + min(args.workers, target - len(records))]
            cursor += len(chunk)
            futures = [
                executor.submit(
                    render_candidate,
                    candidate,
                    class_name,
                    destination,
                    cache_dir,
                    args,
                )
                for candidate in chunk
            ]
            for candidate, future in zip(chunk, futures):
                try:
                    rendered_candidate, path = future.result()
                except QualityRejected as error:
                    rejections.append({
                        "source_id": candidate.source_id, "class": class_name,
                        "longitude": candidate.longitude, "latitude": candidate.latitude,
                        "reasons": "|".join(error.reasons), **error.metrics,
                    })
                    if len(rejected_preview) < 24:
                        rejected_preview.append((error.image, "|".join(error.reasons)))
                    if len(rejections) == 1 or len(rejections) % 25 == 0:
                        print(f"{class_name}: odrzucono jakościowo {len(rejections)}; ostatnio: {error}", flush=True)
                    continue
                except (OSError, requests.RequestException, RuntimeError, ValueError) as error:
                    failures.append(f"{candidate.source_id}: {error}")
                    continue
                records.append(
                    {
                        "image_path": str(path.relative_to(output_dir)),
                        "class": class_name,
                        "label": label,
                        "source_id": rendered_candidate.source_id,
                        "longitude": f"{rendered_candidate.longitude:.8f}",
                        "latitude": f"{rendered_candidate.latitude:.8f}",
                        "area_m2": f"{rendered_candidate.area_m2:.2f}",
                        "width_px": f"{rendered_candidate.width_px:.2f}",
                        "height_px": f"{rendered_candidate.height_px:.2f}",
                        "nearby_buildings": rendered_candidate.nearby_buildings,
                        "center_method": rendered_candidate.center_method,
                        "roof_polygon_px": json.dumps(rendered_candidate.crop_polygon, separators=(",", ":")),
                        **rendered_candidate.quality,
                    }
                )
                print(f"{class_name}: zapisano {len(records)}/{target}", flush=True)
    with (output_dir / f"quality_rejections_{class_name}.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["source_id", "class", "longitude", "latitude", "reasons", *QUALITY_FIELDS])
        writer.writeheader()
        writer.writerows(rejections)
    quality_preview(rejected_preview, output_dir / f"rejected_{class_name}.jpg")
    if len(records) < target:
        raise RuntimeError(
            f"Udało się zapisać tylko {len(records)}/{target} obrazów klasy {class_name}. "
            f"Błędy pobierania: {len(failures)}; odrzucone jakościowo: {len(rejections)}. "
            "Zwiększ pulę kandydatów lub sprawdź raport odrzuceń; filtry nie są automatycznie osłabiane."
        )
    return records, failures, rejections


def create_preview(records: list[dict], output_dir: Path) -> None:
    grouped = {
        class_name: [record for record in records if record["class"] == class_name][:5]
        for class_name in ("asbestos", "non_asbestos")
    }
    columns = max(len(grouped["asbestos"]), len(grouped["non_asbestos"]))
    if columns == 0:
        return
    label_height = 20
    preview = Image.new("RGB", (columns * 128, 2 * (128 + label_height)), "white")
    draw = ImageDraw.Draw(preview)
    for row, class_name in enumerate(("asbestos", "non_asbestos")):
        y = row * (128 + label_height)
        draw.text((4, y + 3), class_name, fill="black")
        for column, record in enumerate(grouped[class_name]):
            with Image.open(output_dir / record["image_path"]) as image:
                preview.paste(image.convert("RGB"), (column * 128, y + label_height))
    preview.save(output_dir / "preview.jpg", quality=92)


def write_outputs(
    records: list[dict],
    failures: list[str],
    output_dir: Path,
    args: argparse.Namespace,
    source_stats: dict,
    quality_rejections: list[dict] | None = None,
) -> None:
    fields = [
        "image_path",
        "class",
        "label",
        "source_id",
        "longitude",
        "latitude",
        "area_m2",
        "width_px",
        "height_px",
        "nearby_buildings",
        "center_method",
        "roof_polygon_px",
        *QUALITY_FIELDS,
    ]
    with (output_dir / "metadata.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    configuration = {
        "seed": args.seed,
        "counts": {
            "asbestos": args.asbestos_count,
            "non_asbestos": args.non_asbestos_count,
        },
        "imagery": {
            "url": GOOGLE_TILE_URL,
            "layer": "s",
            "zoom": args.zoom,
            "tile_size": TILE_SIZE,
            "mosaic_tiles": [3, 3],
            "crop_size": [args.crop_size, args.crop_size],
        },
        "selection": {
            "min_area_m2": args.min_area_m2,
            "min_bbox_side_px": args.min_bbox_side_px,
            "require_full_roof_in_crop": False,
            "village_radius_m": args.village_radius_m,
            "min_nearby_buildings": args.min_nearby_buildings,
            "density_cell_m": args.density_cell_m,
            "asbestos_exclusion_buffer_m": args.asbestos_exclusion_buffer_m,
            "asbestos_exclusion_method": "buffered GeoAzbest bbox intersection",
            "min_center_distance_m": args.min_center_distance_m,
        },
        "quality": {
            **quality_settings(args),
            "rejected_counts": dict(Counter(row["class"] for row in quality_rejections or [])),
            "rejection_reasons": dict(Counter(reason for row in quality_rejections or [] for reason in row["reasons"].split("|"))),
            "centering": "centroid inside largest polygon; interior point fallback avoids courtyards and gaps",
        },
        "preprocessing": {
            "saved_images": "RGB uint8 PNG 128x128",
            "normalization": "Fit normalization on the training split only and reuse it unchanged for validation and inference.",
        },
        "sources": {
            "buildings_geojson": str(args.buildings_geojson.resolve()),
            "asbestos_geojson": str(args.asbestos_geojson.resolve()),
        },
        "source_stats": source_stats,
        "download_failures": len(failures),
    }
    (output_dir / "config.json").write_text(
        json.dumps(configuration, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if failures:
        (output_dir / "download_failures.txt").write_text(
            "\n".join(failures) + "\n", encoding="utf-8"
        )
    create_preview(records, output_dir)


def main() -> None:
    args = parse_args()
    required_paths = (args.audit_dataset / "metadata.csv",) if args.audit_dataset else (args.buildings_geojson, args.asbestos_geojson)
    for path in required_paths:
        if not path.expanduser().is_file():
            raise SystemExit(f"Brak pliku: {path}")
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise SystemExit(f"Folder wyjściowy nie jest pusty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.audit_dataset:
        audit_existing_dataset(args.audit_dataset, output_dir, args)
        return
    cache_dir = (
        args.tile_cache.expanduser().resolve()
        if args.tile_cache
        else output_dir / ".tile_cache"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)

    asbestos_pool = args.asbestos_count * args.candidate_pool_multiplier
    non_asbestos_pool = args.non_asbestos_count * args.candidate_pool_multiplier
    asbestos_reservoir = Reservoir(asbestos_pool, random.Random(args.seed + 1))
    non_asbestos_reservoir = Reservoir(non_asbestos_pool, random.Random(args.seed + 2))

    with tempfile.TemporaryDirectory(prefix="roof_dataset_") as temporary_dir:
        connection = sqlite3.connect(Path(temporary_dir) / "asbestos.sqlite")
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        print("Indeksowanie GeoAzbest...", flush=True)
        asbestos_stats = create_asbestos_index(
            connection, args.asbestos_geojson, asbestos_reservoir, args
        )
        print("Skanowanie budynków OSM i liczenie lokalnej gęstości...", flush=True)
        density, osm_stats = scan_osm_buildings(
            connection, args.buildings_geojson, non_asbestos_reservoir, args
        )
        connection.close()

    asbestos_candidates = village_candidates(asbestos_reservoir.items, density, args)
    non_asbestos_candidates = village_candidates(non_asbestos_reservoir.items, density, args)
    selection_rng = random.Random(args.seed + 3)
    asbestos_candidates = spaced_candidates(
        asbestos_candidates, args.min_center_distance_m, selection_rng
    )
    non_asbestos_candidates = spaced_candidates(
        non_asbestos_candidates, args.min_center_distance_m, selection_rng
    )
    print(
        f"Kandydaci po filtrze wioski: azbest={len(asbestos_candidates):,}, "
        f"nie-azbest={len(non_asbestos_candidates):,}",
        flush=True,
    )
    if len(asbestos_candidates) < args.asbestos_count:
        raise SystemExit(
            "Za mało dachów azbestowych. Zmniejsz progi albo zwiększ --candidate-pool-multiplier."
        )
    if len(non_asbestos_candidates) < args.non_asbestos_count:
        raise SystemExit(
            "Za mało dachów nieazbestowych. Zmniejsz progi albo zwiększ --candidate-pool-multiplier."
        )

    asbestos_records, asbestos_failures, asbestos_rejections = download_class(
        asbestos_candidates,
        "asbestos",
        1,
        args.asbestos_count,
        output_dir,
        cache_dir,
        args,
    )
    non_asbestos_records, non_asbestos_failures, non_asbestos_rejections = download_class(
        non_asbestos_candidates,
        "non_asbestos",
        0,
        args.non_asbestos_count,
        output_dir,
        cache_dir,
        args,
    )
    records = asbestos_records + non_asbestos_records
    failures = asbestos_failures + non_asbestos_failures
    write_outputs(
        records,
        failures,
        output_dir,
        args,
        {
            "geoazbest": asbestos_stats,
            "osm": osm_stats,
            "asbestos_reservoir_seen": asbestos_reservoir.seen,
            "non_asbestos_reservoir_seen": non_asbestos_reservoir.seen,
        },
        asbestos_rejections + non_asbestos_rejections,
    )
    print(f"Gotowe: {output_dir}", flush=True)
    print(f"Podgląd: {output_dir / 'preview.jpg'}", flush=True)


if __name__ == "__main__":
    main()
