from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Coordinates(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-85, le=85)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    south_west: Coordinates
    north_east: Coordinates

    @model_validator(mode="after")
    def ordered_corners(self):
        if self.south_west.longitude >= self.north_east.longitude or self.south_west.latitude >= self.north_east.latitude:
            raise ValueError("south_west must be west and south of north_east; antimeridian rectangles are not supported")
        return self

    def bbox(self) -> tuple[float, float, float, float]:
        return self.south_west.longitude, self.south_west.latitude, self.north_east.longitude, self.north_east.latitude

    def area_km2(self) -> float:
        west, south, east, north = self.bbox()
        return 6371.0**2 * math.radians(east - west) * (math.sin(math.radians(north)) - math.sin(math.radians(south)))


class Geometry(BaseModel):
    type: Literal["Polygon", "MultiPolygon"]
    coordinates: list


class PredictionProperties(BaseModel):
    building_id: str
    source_id: str
    building_type: str | None = None
    status: Literal["ok", "low_quality", "imagery_error", "geometry_error"]
    asbestos_probability: float | None = Field(default=None, ge=0, le=1)
    roof_center: Coordinates | None = None
    quality: dict[str, float | str | None] | None = None
    reasons: list[str] = Field(default_factory=list)


class BuildingFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: Geometry
    properties: PredictionProperties


class AnalysisMeta(BaseModel):
    matched: int
    predicted: int
    low_quality: int
    errors: int
    model_id: str
    elapsed_seconds: float
    building_source: str
    attribution: str = "© OpenStreetMap contributors, ODbL; imagery: Google Satellite"
    warning: str = "Model score is not confirmation of asbestos. Database coverage is limited to the imported OSM snapshot."


class AnalysisResponse(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    bbox: tuple[float, float, float, float]
    features: list[BuildingFeature]
    meta: AnalysisMeta
