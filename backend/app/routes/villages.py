"""Spis wsi, dla ktorych mamy wycinki dachow na dysku.

Pusta lista jest poprawna odpowiedzia, a nie bledem: bez `VILLAGES_DIR` (albo z uszkodzonymi danymi)
aplikacja dziala dokladnie jak dotad, a front nie ma dokad skakac. Dlatego ta trasa nigdy nie oddaje
bledu z powodu danych — zrodlem prawdy o tym, co naprawde udalo sie wczytac, jest `app/localcrops.py`.

Liczby w odpowiedzi opisuja **eksport**, nie nasza baze: `crops` to liczba wierszy w `metadata.csv`,
`buildings` to `buildings_in_boundary` z manifestu (czyli takze budynki bez zdjecia — pominiete kadry
maja jeden powod, `NO_GUGIK_6CM_COVERAGE`, i brak pokrycia nie znaczy, ze dachu nie ma).
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.localcrops import Village, index_for

router = APIRouter(tags=["villages"])


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Coordinates(Camel):
    lng: float
    lat: float


class VillageSummary(Camel):
    """Jedna wies z eksportu kadrow GUGiK.

    `sw`/`ne` to obwiednia granicy z `boundary.geojson`, wiec front dostaje gotowy prostokat do
    `fitBounds` i nie musi znac granicy. `gsdM`, `frameM` i daty nalotu sa `null` tylko wtedy, gdy
    metadane ich nie podaja — nie zgadujemy ich, bo to jedyne miejsce, ktore mowi, co widac na kadrze.
    """

    name: str
    folder: str
    sw: Coordinates
    ne: Coordinates
    crops: int
    buildings: int
    gsd_m: float | None
    frame_m: float | None
    acquired_from: str | None
    acquired_to: str | None


class VillagesResponse(Camel):
    villages: list[VillageSummary]


def to_summary(village: Village) -> VillageSummary:
    return VillageSummary(
        name=village.name,
        folder=village.folder,
        sw=Coordinates(lng=village.sw[0], lat=village.sw[1]),
        ne=Coordinates(lng=village.ne[0], lat=village.ne[1]),
        crops=village.crops,
        buildings=village.buildings,
        gsd_m=village.gsd_m,
        frame_m=village.frame_m,
        acquired_from=village.acquired_from,
        acquired_to=village.acquired_to,
    )


@router.get("/villages", response_model=VillagesResponse)
async def villages(request: Request) -> VillagesResponse:
    """Wsie z wycinkami na dysku; pusta lista, gdy `VILLAGES_DIR` nie jest ustawione."""
    return VillagesResponse(villages=[to_summary(village) for village in index_for(request.app).villages])
