from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PredictionRequestBuilding:
    id: str
    geometry: dict[str, Any]


@dataclass(frozen=True)
class PredictionResult:
    building_id: str
    model_name: str
    model_version: str
    probability: float | None
    uncertainty: float | None
    predicted_class: str | None
    explanation_metadata: dict[str, Any]


class RoofPredictionProvider(ABC):
    @abstractmethod
    async def predict_buildings(self, buildings: list[PredictionRequestBuilding], imagery: dict[str, Any]) -> list[PredictionResult]:
        raise NotImplementedError


class NoOpPredictionProvider(RoofPredictionProvider):
    async def predict_buildings(self, buildings: list[PredictionRequestBuilding], imagery: dict[str, Any]) -> list[PredictionResult]:
        return []
