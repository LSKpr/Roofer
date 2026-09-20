from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import ijson
from shapely import from_wkb, to_wkb
from shapely.errors import GEOSException
from shapely.geometry import box, shape
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class Building:
    id: int
    source_id: str
    building_type: str | None
    geometry: BaseGeometry


class TooManyBuildings(ValueError):
    def __init__(self, limit: int):
        super().__init__(f"Rectangle contains more than {limit} buildings; request a smaller rectangle")
        self.limit = limit


def build_database(source: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite database: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".build-db-", dir=destination.parent) as temporary:
        temporary_path = Path(temporary) / "buildings.sqlite"
        connection = sqlite3.connect(temporary_path)
        try:
            connection.executescript("""
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=OFF;
                CREATE TABLE buildings(id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, building_type TEXT, geometry BLOB NOT NULL);
                CREATE VIRTUAL TABLE building_bounds USING rtree(id, min_lon, max_lon, min_lat, max_lat);
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            buildings, bounds = [], []
            count = skipped = total = 0
            extent = [math.inf, math.inf, -math.inf, -math.inf]
            with source.open("rb") as stream:
                for feature in ijson.items(stream, "features.item", use_float=True):
                    total += 1
                    try:
                        geometry = shape(feature["geometry"])
                        west, south, east, north = geometry.bounds
                        valid = geometry.geom_type in {"Polygon", "MultiPolygon"} and not geometry.is_empty and geometry.is_valid
                        valid = valid and all(math.isfinite(value) for value in geometry.bounds) and -180 <= west <= east <= 180 and -85 <= south <= north <= 85
                    except (KeyError, TypeError, ValueError, AttributeError, GEOSException):
                        valid = False
                    if not valid:
                        skipped += 1
                        continue
                    count += 1
                    properties = feature.get("properties") or {}
                    source_id = str(feature.get("id") or properties.get("osm_id") or properties.get("fid") or total)
                    building_type = properties.get("type") or properties.get("building")
                    buildings.append((count, source_id, str(building_type) if building_type else None, to_wkb(geometry)))
                    bounds.append((count, west, east, south, north))
                    extent = [min(extent[0], west), min(extent[1], south), max(extent[2], east), max(extent[3], north)]
                    if len(buildings) >= 5000:
                        connection.executemany("INSERT INTO buildings VALUES (?, ?, ?, ?)", buildings)
                        connection.executemany("INSERT INTO building_bounds VALUES (?, ?, ?, ?, ?)", bounds)
                        connection.commit()
                        buildings.clear()
                        bounds.clear()
                    if count % 100_000 == 0:
                        print(f"Indexed {count:,} buildings", flush=True)
            if not count:
                raise ValueError("No valid Polygon/MultiPolygon features in the input FeatureCollection")
            connection.executemany("INSERT INTO buildings VALUES (?, ?, ?, ?)", buildings)
            connection.executemany("INSERT INTO building_bounds VALUES (?, ?, ?, ?, ?)", bounds)
            info = {
                "schema_version": 1, "source": source.name, "building_count": count,
                "source_features": total, "skipped_invalid": skipped, "coverage_bbox": extent,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "attribution": "© OpenStreetMap contributors, ODbL",
            }
            connection.executemany("INSERT INTO metadata VALUES (?, ?)", [(key, json.dumps(value)) for key, value in info.items()])
            connection.commit()
        finally:
            connection.close()
        os.link(temporary_path, destination)
    return info


class BuildingStore:
    def __init__(self, path: Path):
        self.path = path.resolve()
        connection = self.connect()
        try:
            self.info = {key: json.loads(value) for key, value in connection.execute("SELECT key, value FROM metadata")}
        finally:
            connection.close()
        if self.info.get("schema_version") != 1 or self.info.get("building_count", 0) < 1:
            raise ValueError("Unsupported or empty buildings database")

    def connect(self):
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=10)
        connection.execute("PRAGMA query_only=ON")
        return connection

    def query(self, bbox: tuple[float, float, float, float], limit: int) -> list[Building]:
        west, south, east, north = bbox
        rectangle = box(west, south, east, north)
        result = []
        connection = self.connect()
        try:
            rows = connection.execute("""
                SELECT b.id, b.source_id, b.building_type, b.geometry
                FROM building_bounds r JOIN buildings b ON b.id = r.id
                WHERE r.min_lon <= ? AND r.max_lon >= ? AND r.min_lat <= ? AND r.max_lat >= ?
            """, (east, west, north, south))
            for identity, source_id, building_type, encoded in rows:
                geometry = from_wkb(encoded)
                if not geometry.intersects(rectangle):
                    continue
                result.append(Building(identity, source_id, building_type, geometry))
                if len(result) > limit:
                    raise TooManyBuildings(limit)
        finally:
            connection.close()
        return sorted(result, key=lambda building: building.id)
