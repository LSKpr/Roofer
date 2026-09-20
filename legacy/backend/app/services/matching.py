from dataclasses import dataclass
from typing import Any

from shapely.geometry.base import BaseGeometry

from app.services.geo import to_2180


@dataclass(frozen=True)
class BuildingCandidate:
    source_id: str
    geometry: BaseGeometry
    tags: dict[str, Any]


@dataclass(frozen=True)
class RegistryCandidate:
    source_id: str
    geometry: BaseGeometry
    location_id: str | None
    parcel_number: str | None
    status: str


@dataclass(frozen=True)
class MatchDecision:
    registry_source_id: str
    match_method: str
    intersection_area_m2: float
    overlap_ratio: float
    confidence: float
    ambiguity_flag: bool


def _first_tag(tags: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = tags.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def overlap_metrics(building: BaseGeometry, registry: BaseGeometry) -> tuple[float, float]:
    building_2180 = to_2180(building)
    registry_2180 = to_2180(registry)
    intersection_area = building_2180.intersection(registry_2180).area
    if building_2180.area <= 0:
        return 0.0, 0.0
    return intersection_area, min(1.0, intersection_area / building_2180.area)


def match_building(building: BuildingCandidate, records: list[RegistryCandidate]) -> list[MatchDecision]:
    location_id = _first_tag(building.tags, "geoazbest:location_id", "id_lok", "id_lokalizacji")
    parcel_number = _first_tag(building.tags, "parcel_number", "nr_dzialki", "ref:parcel")
    candidates: list[tuple[RegistryCandidate, str, float, float, float]] = []
    for record in records:
        intersection_area, overlap = overlap_metrics(building.geometry, record.geometry)
        if intersection_area <= 0:
            continue
        if location_id and record.location_id == location_id:
            method, confidence = "location_id_spatial", 0.99
        elif parcel_number and record.parcel_number == parcel_number:
            method, confidence = "parcel_number_spatial", min(0.9, 0.7 + overlap * 0.2)
        else:
            method, confidence = "spatial_intersection", min(0.88, 0.35 + overlap * 0.55)
        candidates.append((record, method, intersection_area, overlap, confidence))
    candidates.sort(key=lambda item: (item[4], item[3], item[2]), reverse=True)
    ambiguous = len(candidates) > 1 and abs(candidates[0][4] - candidates[1][4]) < 0.15
    return [
        MatchDecision(record.source_id, method, area, overlap, confidence, ambiguous)
        for record, method, area, overlap, confidence in candidates
    ]


def aggregate_status(decisions: list[MatchDecision], records: dict[str, RegistryCandidate], registry_available: bool) -> str:
    if not registry_available:
        return "unknown"
    if not decisions:
        return "not_listed"
    statuses = {records[decision.registry_source_id].status for decision in decisions}
    if "listed" in statuses and "cleaned" in statuses:
        return "ambiguous"
    if any(decision.ambiguity_flag for decision in decisions):
        return "ambiguous"
    if "listed" in statuses:
        return "listed"
    if "cleaned" in statuses:
        return "cleaned"
    return "unknown"
