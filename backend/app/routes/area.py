from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.area import (
    MAX_AREA_KM2,
    MAX_LISTED_BUILDINGS,
    AreaScan,
    BoundingBox,
    area_problem,
    bbox_area_km2,
    bbox_problem,
    scan_area,
)

router = APIRouter(tags=["area"])


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Coordinates(Camel):
    lng: float = Field(ge=-180.0, le=180.0)
    lat: float = Field(ge=-90.0, le=90.0)


class ScanRequest(Camel):
    """Prostokat zaznaczony na mapie: naroznik polnocno-wschodni i poludniowo-zachodni."""

    ne: Coordinates
    sw: Coordinates


class Stats(Camel):
    """`not_listed` znaczy „nie ma go w rejestrze", a nie „dach jest czysty"."""

    total: int
    listed: int
    not_listed: int
    listed_share: float
    roof_area_m2: float
    listed_roof_area_m2: float
    registry_records: int


class ListedBuilding(Camel):
    id: int
    """`osm_id`, czyli ten sam adres, ktorym wola sie `/api/buildings/{id}` i ten sam, ktory niesie
    kafel. Ksztalt odpowiedzi jest bez zmian — zmienilo sie tylko znaczenie tej liczby."""
    area_m2: float
    centroid: Coordinates
    nr_dzialki: str | None = None


class ScanResponse(Camel):
    stats: Stats
    listed_buildings: list[ListedBuilding]
    truncated: bool
    area_km2: float


class AreaLimits(Camel):
    """Front pyta o limit, zamiast trzymac wlasna kopie liczby, ktora zna tylko backend."""

    max_area_km2: float


def to_bounding_box(body: ScanRequest) -> BoundingBox:
    return BoundingBox(south=body.sw.lat, west=body.sw.lng, north=body.ne.lat, east=body.ne.lng)


def to_listed_building(item: dict[str, Any]) -> ListedBuilding:
    """Klucze przychodza z json_build_object w AREA_SCAN_SQL, wiec sa juz w camelCase."""
    return ListedBuilding(
        id=item["id"],
        area_m2=item["areaM2"],
        centroid=Coordinates(lng=item["lng"], lat=item["lat"]),
        nr_dzialki=item.get("nrDzialki"),
    )


def to_response(scan: AreaScan) -> ScanResponse:
    return ScanResponse(
        stats=Stats(
            total=scan.stats.total,
            listed=scan.stats.listed,
            not_listed=scan.stats.not_listed,
            listed_share=scan.stats.listed_share,
            roof_area_m2=scan.stats.roof_area_m2,
            listed_roof_area_m2=scan.stats.listed_roof_area_m2,
            registry_records=scan.stats.registry_records,
        ),
        listed_buildings=[to_listed_building(item) for item in scan.listed_buildings],
        truncated=scan.truncated,
        area_km2=scan.area_km2,
    )


@router.get("/area/limits", response_model=AreaLimits)
async def limits() -> AreaLimits:
    return AreaLimits(max_area_km2=MAX_AREA_KM2)


@router.post("/area/scan", response_model=ScanResponse, responses={400: {}, 503: {}})
async def scan(body: ScanRequest, request: Request) -> ScanResponse:
    bbox = to_bounding_box(body)
    problem = bbox_problem(bbox)
    if problem is not None:
        raise HTTPException(status_code=400, detail=problem)

    area_km2 = bbox_area_km2(bbox)
    too_large = area_problem(area_km2)
    if too_large is not None:  # bramka przed baza: za duzego zaznaczenia nawet nie odpytujemy
        raise HTTPException(status_code=400, detail=too_large)

    settings = request.app.state.settings
    try:
        result = await scan_area(request.app.state.pool, bbox, settings.database_timeout_s, MAX_LISTED_BUILDINGS)
    except Exception as error:  # padnieta baza to 503, nie 500 z tracebackiem
        raise HTTPException(status_code=503, detail="Baza nie odpowiada.") from error
    return to_response(result)
