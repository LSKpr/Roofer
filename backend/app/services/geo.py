from collections.abc import Iterable
from typing import Any

from pyproj import Transformer
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

TO_2180 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)
TO_4326 = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)


def as_geometry(value: dict[str, Any] | BaseGeometry) -> BaseGeometry:
    return value if isinstance(value, BaseGeometry) else shape(value)


def validate_polygon(value: dict[str, Any] | BaseGeometry) -> Polygon | MultiPolygon:
    geometry = as_geometry(value)
    if not isinstance(geometry, (Polygon, MultiPolygon)):
        raise ValueError("Expected Polygon or MultiPolygon geometry")
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("Geometry must be non-empty and valid")
    return geometry


def to_2180(geometry: BaseGeometry) -> BaseGeometry:
    return transform(TO_2180.transform, geometry)


def to_4326(geometry: BaseGeometry) -> BaseGeometry:
    return transform(TO_4326.transform, geometry)


def area_km2(geometry: BaseGeometry) -> float:
    return to_2180(geometry).area / 1_000_000


def bbox_string(geometry: BaseGeometry) -> str:
    min_x, min_y, max_x, max_y = geometry.bounds
    return f"{min_x:.7f},{min_y:.7f},{max_x:.7f},{max_y:.7f}"


def geojson_mapping(geometry: BaseGeometry) -> dict[str, Any]:
    return geometry.__geo_interface__


def polygonal(geometries: Iterable[BaseGeometry]) -> list[Polygon | MultiPolygon]:
    return [geometry for geometry in geometries if isinstance(geometry, (Polygon, MultiPolygon)) and not geometry.is_empty]
