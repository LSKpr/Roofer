import asyncio
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx
from shapely.geometry import Polygon

from app.config import Settings

GUGIK_WMS_CURRENT = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution"
GUGIK_WMS_TIME = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolutionTime"
GUGIK_WMS_CURRENT_DETAIL = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution"
GUGIK_WMS_TIME_DETAIL = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolutionTime"
DETAIL_MIN_ZOOM = 16
GUGIK_INDEX_WFS = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WFS/Skorowidze"
GUGIK_ATTRIBUTION = "Orthophotomap: GUGiK / Geoportal.gov.pl"
GUGIK_LICENSE = "Service use is subject to Geoportal terms. WMTS capabilities prohibit automated harvesting; this application requests only viewport tiles and preserves attribution. Recheck terms before redistribution."


@dataclass(frozen=True)
class ImageryDescriptor:
    id: str
    provider: str
    layer_id: str
    acquisition_year: int
    acquisition_date_range: str | None
    resolution_m: float | None
    coverage: dict[str, Any] | None
    attribution: str
    license_metadata: str
    service_configuration: dict[str, Any]
    verified_for_area: bool


class ImageryProvider(ABC):
    @abstractmethod
    async def available_for_area(self, area: Polygon) -> list[ImageryDescriptor]:
        raise NotImplementedError


class GugikImageryProvider(ImageryProvider):
    def __init__(self, settings: Settings):
        self.timeout = settings.external_timeout_seconds

    async def available_for_area(self, area: Polygon) -> list[ImageryDescriptor]:
        current = ImageryDescriptor(
            id="gugik-ortho-current",
            provider="GUGiK Geoportal",
            layer_id="Raster",
            acquisition_year=2025,
            acquisition_date_range="Date varies by sheet; inspect GetFeatureInfo for exact source metadata.",
            resolution_m=None,
            coverage=None,
            attribution=GUGIK_ATTRIBUTION,
            license_metadata=GUGIK_LICENSE,
            service_configuration={"kind": "wms", "url": GUGIK_WMS_CURRENT, "layers": "Raster", "version": "1.3.0", "detail_url": GUGIK_WMS_CURRENT_DETAIL},
            verified_for_area=True,
        )
        years = list(range(2012, 2026))
        semaphore = asyncio.Semaphore(3)

        async def verify(year: int) -> ImageryDescriptor | None:
            async with semaphore:
                if await self._index_covers(area, year):
                    return self._timed_layer(year)
            return None

        results = await asyncio.gather(*(verify(year) for year in years), return_exceptions=True)
        historical = [result for result in results if isinstance(result, ImageryDescriptor)]
        return historical or [current]

    async def _index_covers(self, area: Polygon, year: int) -> bool:
        min_lon, min_lat, max_lon, max_lat = area.bounds
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": f"gugik:SkorowidzOrtofomapy{year}",
            "resultType": "hits",
            "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat},EPSG:4326",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(GUGIK_INDEX_WFS, params=params)
                response.raise_for_status()
                text = response.text
        except httpx.HTTPError:
            return False
        marker = "numberMatched=\""
        if marker not in text:
            return False
        value = text.split(marker, 1)[1].split("\"", 1)[0]
        return value.isdigit() and int(value) > 0

    @staticmethod
    def _timed_layer(year: int) -> ImageryDescriptor:
        return ImageryDescriptor(
            id=f"gugik-ortho-{year}",
            provider="GUGiK Geoportal",
            layer_id="Raster",
            acquisition_year=year,
            acquisition_date_range=f"{year}; spatial coverage confirmed against the official GUGiK orthophoto index.",
            resolution_m=None,
            coverage=None,
            attribution=GUGIK_ATTRIBUTION,
            license_metadata=GUGIK_LICENSE,
            service_configuration={"kind": "wms", "url": GUGIK_WMS_TIME, "layers": "Raster", "time": f"{year}-01-01T00:00:00.000Z", "version": "1.3.0", "detail_url": GUGIK_WMS_TIME_DETAIL},
            verified_for_area=True,
        )


def mercator_tile_bbox_4326(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2**z
    lon_left = x / n * 360.0 - 180.0
    lon_right = (x + 1) / n * 360.0 - 180.0

    def latitude(tile_y: int) -> float:
        radians = math.atan(math.sinh(math.pi * (1 - 2 * tile_y / n)))
        return math.degrees(radians)

    lat_top = latitude(y)
    lat_bottom = latitude(y + 1)
    return lon_left, lat_bottom, lon_right, lat_top


def wms_tile_parameters(layer: ImageryDescriptor, z: int, x: int, y: int) -> tuple[str, dict[str, str]]:
    min_lon, min_lat, max_lon, max_lat = mercator_tile_bbox_4326(z, x, y)
    config = layer.service_configuration
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": str(config["layers"]),
        "STYLES": "",
        "CRS": "EPSG:4326",
        "BBOX": f"{min_lat},{min_lon},{max_lat},{max_lon}",
        "WIDTH": "256",
        "HEIGHT": "256",
        "FORMAT": "image/jpeg",
        "TRANSPARENT": "FALSE",
    }
    if config.get("time"):
        params["TIME"] = str(config["time"])
    return str(config["url"]), params


def tile_request_candidates(layer: ImageryDescriptor, z: int, x: int, y: int) -> list[tuple[str, dict[str, str]]]:
    """Official GUGiK services to try for one tile, in priority order.

    The nationwide standard-resolution service gives continuous country-scale coverage, while the
    high-resolution service is sharper but intentionally discontinuous. Neither covers every tile at
    every zoom, so both are tried: nationwide first when zoomed out, detailed first from building
    zoom upward. A tile is therefore always real official imagery, or an explicit failure.
    """
    url, params = wms_tile_parameters(layer, z, x, y)
    detail_url = layer.service_configuration.get("detail_url")
    if not detail_url:
        return [(url, params)]
    detail = (str(detail_url), params)
    nationwide = (url, params)
    return [detail, nationwide] if z >= DETAIL_MIN_ZOOM else [nationwide, detail]


def build_imagery_provider(settings: Settings) -> ImageryProvider:
    return GugikImageryProvider(settings)
