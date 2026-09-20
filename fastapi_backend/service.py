from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from shapely import to_geojson

from Data.build_roof_dataset import QUALITY_DEFAULTS, assess_image_quality, geometry_polygons, polygon_mask, roof_center, valid_ring, world_pixel

from .database import Building, BuildingStore
from .imagery import ImageryError, SatelliteTiles
from .inference import RoofModel
from .schemas import BuildingFeature, Coordinates, Geometry, PredictionProperties
from .settings import Settings


class AnalysisService:
    def __init__(self, settings: Settings, store=None, model=None, tiles=None):
        self.settings = settings
        self.store = store or BuildingStore(settings.database_path)
        self.model = model or RoofModel(settings.model_path, settings.model_threads)
        self.tiles = tiles or SatelliteTiles(settings)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="roof-inference")

    async def prepare(self, building: Building):
        geometry = json.loads(to_geojson(building.geometry))
        identity = f"osm:{building.id}"
        feature = BuildingFeature(
            id=identity, geometry=Geometry(**geometry),
            properties=PredictionProperties(building_id=identity, source_id=building.source_id, building_type=building.building_type, status="geometry_error"),
        )
        selected = roof_center(geometry_polygons(geometry))
        if selected is None:
            feature.properties.reasons = ["NO_INTERIOR_ROOF_POINT"]
            return feature, None
        (longitude, latitude), polygon, _ = selected
        feature.properties.roof_center = Coordinates(longitude=longitude, latitude=latitude)
        try:
            image, (origin_x, origin_y) = await self.tiles.crop(longitude, latitude)
        except ImageryError as error:
            feature.properties.status = "imagery_error"
            feature.properties.reasons = [str(error)]
            return feature, None
        projected = [
            [[x - origin_x, y - origin_y] for x, y in (world_pixel(*point, 20) for point in valid_ring(ring))]
            for ring in polygon
        ]
        quality, reasons = assess_image_quality(image, polygon_mask(projected, image.size), SimpleNamespace(**QUALITY_DEFAULTS))
        feature.properties.quality = quality
        feature.properties.reasons = reasons
        feature.properties.status = "low_quality" if reasons else "ok"
        return feature, None if reasons else image

    async def analyze(self, buildings: list[Building]) -> list[BuildingFeature]:
        result = []
        loop = asyncio.get_running_loop()
        for start in range(0, len(buildings), self.settings.batch_size):
            prepared = await asyncio.gather(*(self.prepare(building) for building in buildings[start : start + self.settings.batch_size]))
            valid = [(feature, image) for feature, image in prepared if image is not None]
            if valid:
                probabilities = await loop.run_in_executor(self.executor, self.model.predict, [image for _, image in valid])
                for (feature, _), probability in zip(valid, probabilities, strict=True):
                    feature.properties.asbestos_probability = probability
            result.extend(feature for feature, _ in prepared)
        return result

    async def close(self):
        await self.tiles.close()
        self.executor.shutdown(wait=True, cancel_futures=True)
