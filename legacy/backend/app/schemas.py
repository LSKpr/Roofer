from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


GeometryDict = dict[str, Any]
Status = Literal["listed", "cleaned", "not_listed", "ambiguous", "unknown"]


class AnalysisRequest(BaseModel):
    geometry: GeometryDict
    requested_years: list[int] = Field(default_factory=list, max_length=2)

    @field_validator("geometry")
    @classmethod
    def require_polygon(cls, value: GeometryDict) -> GeometryDict:
        if value.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("Analysis geometry must be a Polygon or MultiPolygon")
        if not value.get("coordinates"):
            raise ValueError("Analysis geometry has no coordinates")
        return value


class AnalysisJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    progress: int
    stage: str
    counts: dict[str, Any]
    errors: list[dict[str, str]]
    registry_source_status: str
    started_at: datetime | None
    completed_at: datetime | None


class RegistryEvidence(BaseModel):
    match_id: UUID
    source_feature_id: str
    source_layer: str
    status: str
    location_id: str | None
    parcel_number: str | None
    teryt: str | None
    urgency: str | None
    planned_removal_year: int | None
    actual_removal_year: int | None
    inventory_amount: float | None
    disposed_amount: float | None
    synchronized_at: datetime
    match_method: str
    intersection_area_m2: float
    overlap_ratio: float
    confidence: float
    ambiguous: bool
    manually_reviewed: bool


class BuildingProperties(BaseModel):
    id: UUID
    status: Status
    source_provider: str
    source_object_type: str
    source_object_id: str
    osm_tags: dict[str, Any]
    match_confidence: float | None
    has_before_after_imagery: bool = False
    manual_reviewed: bool = False
    registry_source_status: str = "available"


class BuildingDetail(BaseModel):
    id: UUID
    status: Status
    geometry: GeometryDict
    source_provider: str
    source_object_type: str
    source_object_id: str
    osm_tags: dict[str, Any]
    evidence: list[RegistryEvidence]
    warnings: list[str]
    selected_imagery_year: int | None = None
    data_source_timestamps: dict[str, str | None]


class ImageryLayerResponse(BaseModel):
    id: str
    provider: str
    layer_id: str
    acquisition_year: int
    acquisition_date_range: str | None
    resolution_m: float | None
    coverage: GeometryDict | None
    attribution: str
    license_metadata: str
    service_configuration: dict[str, Any]
    verified_for_area: bool


class ReviewRequest(BaseModel):
    reviewed: bool
    note: str | None = Field(default=None, max_length=2000)


class SyncRequest(BaseModel):
    layer: Literal["wfs:budynki_z_azbestem", "wfs:budynki_oczyszczone", "wfs:budynki", "wfs:wyroby_dzialki", "wfs:wyroby_rury"]
    bbox: list[float] | None = None
    teryt: str | None = None
    full_country: bool = False

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and (len(value) != 4 or value[0] >= value[2] or value[1] >= value[3]):
            raise ValueError("bbox must be [minLon, minLat, maxLon, maxLat]")
        return value


class SyncResponse(BaseModel):
    checkpoint_id: UUID
    status: str
    processed_count: int
    total_expected: int | None
    next_start_index: int


class StatisticsResponse(BaseModel):
    total_osm_buildings: int = 0
    registry_listed_asbestos_buildings: int = 0
    cleaned_buildings: int = 0
    not_listed_buildings: int = 0
    ambiguous_matches: int = 0
    unknown_buildings: int = 0
    records_with_removal_years: int = 0
    records_with_incomplete_metadata: int = 0


class ModelPredictionResponse(BaseModel):
    building_id: UUID
    imagery_layer_id: UUID
    model_name: str
    model_version: str
    probability: float | None
    uncertainty: float | None
    predicted_class: str | None
    explanation_metadata: dict[str, Any]
    created_at: datetime


class GeocodeResult(BaseModel):
    label: str
    center: tuple[float, float]
    bbox: list[float]
