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
    """`osm_id` z OpenStreetMap, nie klucz z sekwencji bazy: tylko ten przezywa ponowny import.

    Osobnego `osmId` tu nie ma i nie ma go byc — po zmianie adresowania bylaby to ta sama liczba
    raz jako liczba, raz jako napis, i nic nie mowiloby, ktora jest adresem budynku.
    """
    kind: str | None
    """Rodzaj z OSM (`type`): house, apartments, outbuilding, garage. None, gdy nie podano."""
    osm_type: str | None
    name: str | None
    area_m2: float
    centroid: Coordinates
    status: Literal["listed", "not_listed"]
    registry_matches: list[RegistryMatch]
    other_intersecting: int


def to_building(row: dict[str, Any]) -> Building:
    return Building(
        id=row["id"],  # kolumna `id` w BUILDING_SQL to osm_id::bigint, nie klucz z sekwencji
        kind=row["fclass"],
        osm_type=row["osm_type"],
        name=row["name"],
        area_m2=row["area_m2"],
        centroid=Coordinates(lng=row["lng"], lat=row["lat"]),
        status="listed" if row["registry_matches"] > 0 else "not_listed",
        registry_matches=[RegistryMatch.model_validate(record) for record in row["records"]],
        other_intersecting=row["other_intersecting"],
    )


@router.get("/buildings/{osm_id}", response_model=Building)
async def building(osm_id: int, request: Request) -> Building:
    """Adresem budynku jest `osm_id`. Typ `int` zostaje, bo walidacje ma robic FastAPI, a nie SQL:
    zamiast 500 z bazy dostajemy 422 na „/api/buildings/abc". Do zapytania parametr idzie rzutowany
    na `text`, zeby zadzialal indeks po kolumnie tekstowej (patrz app/buildings.py)."""
    settings = request.app.state.settings
    try:
        row = await read_building(request.app.state.pool, osm_id, settings.database_timeout_s)
    except Exception as error:  # padnieta baza to 503, nie 500 z traceba w logu
        raise HTTPException(status_code=503, detail="Baza nie odpowiada.") from error
    if row is None:
        raise HTTPException(status_code=404, detail="Nie ma budynku o tym identyfikatorze.")
    return to_building(row)
