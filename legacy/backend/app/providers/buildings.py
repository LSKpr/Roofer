from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from shapely.geometry import LineString, MultiPolygon, Polygon, shape
from shapely.ops import polygonize, unary_union
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.fixtures.demo import DEMO_BUILDINGS
from app.services.geo import validate_polygon


class ExternalBuildingServiceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildingRecord:
    object_type: str
    object_id: str
    geometry: Polygon | MultiPolygon
    tags: dict[str, Any]
    source_updated_at: datetime | None = None


class BuildingProvider(ABC):
    @abstractmethod
    async def fetch_buildings(self, area: Polygon | MultiPolygon) -> list[BuildingRecord]:
        raise NotImplementedError


class OverpassBuildingProvider(BuildingProvider):
    def __init__(self, settings: Settings):
        self.url = settings.overpass_url
        self.timeout = settings.external_timeout_seconds

    async def fetch_buildings(self, area: Polygon | MultiPolygon) -> list[BuildingRecord]:
        min_lon, min_lat, max_lon, max_lat = area.bounds
        bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
        query = f"""[out:json][timeout:25];
(
  way[\"building\"]({bbox});
  relation[\"building\"]({bbox});
  relation[\"type\"=\"multipolygon\"][\"building\"]({bbox});
);
out body geom;
>;
out body geom;"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": "Roofer/0.1 contact: demo@example.invalid"}) as client:
                response = await client.post(self.url, data={"data": query})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ExternalBuildingServiceUnavailable(str(error)) from error
        return self._parse(payload.get("elements", []), area)

    def _parse(self, elements: list[dict[str, Any]], area: Polygon | MultiPolygon) -> list[BuildingRecord]:
        ways = {str(element["id"]): element for element in elements if element.get("type") == "way"}
        records: list[BuildingRecord] = []
        emitted: set[tuple[str, str]] = set()
        for element in elements:
            element_type = element.get("type")
            tags = element.get("tags") or {}
            if element_type == "way" and "building" in tags:
                geometry = self._way_polygon(element)
            elif element_type == "relation" and "building" in tags:
                geometry = self._relation_geometry(element, ways)
            else:
                continue
            if geometry is None or geometry.is_empty or not geometry.intersects(area):
                continue
            key = (element_type, str(element["id"]))
            if key not in emitted:
                records.append(BuildingRecord(key[0], key[1], geometry, tags))
                emitted.add(key)
        return records

    @staticmethod
    def _way_polygon(element: dict[str, Any]) -> Polygon | None:
        coordinates = [(point["lon"], point["lat"]) for point in element.get("geometry", [])]
        if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
            return None
        polygon = Polygon(coordinates)
        return polygon if polygon.is_valid and polygon.area > 0 else None

    def _relation_geometry(self, relation: dict[str, Any], ways: dict[str, dict[str, Any]]) -> Polygon | MultiPolygon | None:
        outer_lines: list[LineString] = []
        inner_lines: list[LineString] = []
        for member in relation.get("members", []):
            if member.get("type") != "way":
                continue
            way = ways.get(str(member.get("ref")))
            if not way:
                continue
            coordinates = [(point["lon"], point["lat"]) for point in way.get("geometry", [])]
            if len(coordinates) < 2:
                continue
            (inner_lines if member.get("role") == "inner" else outer_lines).append(LineString(coordinates))
        if not outer_lines:
            return None
        outer_polygons = list(polygonize(unary_union(outer_lines)))
        inner_polygons = list(polygonize(unary_union(inner_lines)))
        constructed = []
        for outer in outer_polygons:
            holes = [list(inner.exterior.coords) for inner in inner_polygons if outer.contains(inner.representative_point())]
            constructed.append(Polygon(outer.exterior.coords, holes))
        if not constructed:
            return None
        return constructed[0] if len(constructed) == 1 else MultiPolygon(constructed)


class DemoBuildingProvider(BuildingProvider):
    async def fetch_buildings(self, area: Polygon | MultiPolygon) -> list[BuildingRecord]:
        return [
            BuildingRecord(item["type"], item["id"], validate_polygon(item["geometry"]), item["tags"])
            for item in DEMO_BUILDINGS
            if validate_polygon(item["geometry"]).intersects(area)
        ]


class LocalOsmBuildingProvider(BuildingProvider):
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def fetch_buildings(self, area: Polygon | MultiPolygon) -> list[BuildingRecord]:
        min_lon, min_lat, max_lon, max_lat = area.bounds
        sql = text("""
            SELECT osm_type, osm_id::text, tags, ST_AsGeoJSON(geometry) AS geometry, source_updated_at
            FROM local_osm_buildings
            WHERE geometry && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
              AND ST_Intersects(geometry, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))
        """)
        with self.session_factory() as session:
            rows = session.execute(sql, {"min_lon": min_lon, "min_lat": min_lat, "max_lon": max_lon, "max_lat": max_lat}).mappings().all()
        return [
            BuildingRecord(str(row["osm_type"]), row["osm_id"], validate_polygon(shape(row["geometry"])), row["tags"] or {}, row["source_updated_at"])
            for row in rows
        ]


def build_provider(settings: Settings, session_factory) -> BuildingProvider:
    if settings.building_provider == "local_postgis":
        return LocalOsmBuildingProvider(session_factory)
    if settings.building_provider == "demo_fixture":
        return DemoBuildingProvider()
    return OverpassBuildingProvider(settings)
