from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.buildings import read_building
from app.localcrops import RoofCrop, index_for

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


class RoofImage(Camel):
    """Ktory kadr oddaje `/api/buildings/{osm_id}/roof.png` dla tego budynku — i co o nim wiadomo.

    To pole istnieje po to, zeby podpis w karcie budynku mowil prawde o zdjeciu, ktore wlasnie widac.
    Dwa zrodla to dwa rozne kadry i nie wolno ich mieszac bez powiedzenia, ktory jest ktory:

    * `local` — wycinek z eksportu autora modelu: stale **12,8 x 12,8 m** wycentrowane na budynku
      przy 5 cm na piksel, z konkretna data nalotu. Dach dluzszy niz 13 m jest w tym kadrze
      **przyciety**, wiec z obrazka nie wolno czytac wielkosci budynku.
    * `wms` — nasz wlasny wycinek z ortofotomapy GUGiK: kwadrat z marginesem wokol **calego**
      budynku, ale bez daty nalotu i bez rodzimej rozdzielczosci. Dlatego przy `wms` wszystkie trzy
      liczby sa `null`: nie znamy ich, a zgadywanie byloby wymyslaniem metadanych.
    """

    source: Literal["local", "wms"]
    gsd_m: float | None
    """Rodzima rozdzielczosc kadru w metrach na piksel (0.05 przy eksporcie, `null` przy WMS-ie)."""
    frame_m: float | None
    """Bok kadru w metrach (12.8 przy eksporcie, `null` przy WMS-ie — tam zalezy od budynku)."""
    acquired_on: str | None
    """Data nalotu w ISO, jesli metadane ja podaja."""


# Jeden obiekt na wszystkie odpowiedzi „kadr z WMS-a": pydantic i tak nie pozwoli go zmienic w miejscu,
# a trzy `None` wypisane raz sa czytelniejsze niz trzy `None` powtarzane w kazdej trasie.
WMS_ROOF_IMAGE = RoofImage(source="wms", gsd_m=None, frame_m=None, acquired_on=None)


def roof_image_of(crop: RoofCrop | None) -> RoofImage:
    """Opis kadru, ktory naprawde pojdzie do przegladarki: z dysku, gdy go mamy, inaczej z WMS-a."""
    if crop is None:
        return WMS_ROOF_IMAGE
    return RoofImage(source="local", gsd_m=crop.gsd_m, frame_m=crop.frame_m, acquired_on=crop.acquired_on)


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
    roof_image: RoofImage
    """Zawsze obecne: karta budynku pisze z tego pola podpis pod zdjeciem dachu."""


def to_building(row: dict[str, Any], roof_image: RoofImage) -> Building:
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
        roof_image=roof_image,
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
        raise HTTPException(status_code=503, detail="The database is not responding.") from error
    if row is None:
        raise HTTPException(status_code=404, detail="There is no building with this identifier.")
    # Indeks kadrow z dysku jest w pamieci procesu (wczytany raz), wiec to sprawdzenie nie kosztuje
    # ani zapytania do bazy, ani odczytu pliku — a bez niego karta nie wiedzialaby, co pokazuje.
    return to_building(row, roof_image_of(index_for(request.app).find(osm_id)))
