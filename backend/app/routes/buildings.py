from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.buildings import read_building

router = APIRouter(tags=["buildings"])


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Coordinates(Camel):
    lng: float
    lat: float


class RegistryMatch(Camel):
    """Rekord rejestru dopasowany do budynku, razem z miara dopasowania."""

    source_id: str | None
    nr_dzialki: str | None
    record_area_m2: float
    overlap_m2: float
    share_building: float
    share_record: float


class Building(Camel):
    """`not_listed` znaczy „nie ma go w rejestrze", a nie „dach jest czysty"."""

    id: int
    osm_id: str | None
    kind: str | None
    name: str | None
    area_m2: float
    centroid: Coordinates
    status: Literal["listed", "not_listed"]
    registry_matches: list[RegistryMatch]
    other_intersecting: int


def to_building(row: dict[str, Any]) -> Building:
    return Building(
        id=row["id"],
        osm_id=row["osm_id"],
        kind=row["fclass"],
        name=row["name"],
        area_m2=row["area_m2"],
        centroid=Coordinates(lng=row["lng"], lat=row["lat"]),
        status="listed" if row["registry_matches"] > 0 else "not_listed",
        registry_matches=[RegistryMatch.model_validate(record) for record in row["records"]],
        other_intersecting=row["other_intersecting"],
    )


@router.get("/buildings/{building_id}", response_model=Building)
async def building(building_id: int, request: Request) -> Building:
    settings = request.app.state.settings
    try:
        row = await read_building(request.app.state.pool, building_id, settings.database_timeout_s)
    except Exception as error:  # padnieta baza to 503, nie 500 z traceba w logu
        raise HTTPException(status_code=503, detail="Baza nie odpowiada.") from error
    if row is None:
        raise HTTPException(status_code=404, detail="Nie ma budynku o tym identyfikatorze.")
    return to_building(row)
