from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.geocode import DEFAULT_LIMIT, MAX_LIMIT, GeocodeError, get_geocoder

router = APIRouter(tags=["geocode"])


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Place(Camel):
    """Jedno miejsce z Nominatima. `bbox` jest w kolejnosci [south, west, north, east]."""

    label: str
    lat: float
    lng: float
    bbox: list[float] | None = None
    kind: str | None = None


class PlaceResults(Camel):
    results: list[Place]


@router.get("/geocode", response_model=PlaceResults, responses={400: {}, 429: {}, 503: {}})
async def geocode(
    request: Request,
    q: Annotated[str, Query(description="Nazwa miejscowosci albo adres")] = "",
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> PlaceResults:
    geocoder = get_geocoder(request.app)
    try:
        places = await geocoder.search(q, limit)
    except GeocodeError as error:  # 400 dla pustej frazy, 429 dla limitu, 503 dla padnietego zrodla
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    return PlaceResults(results=[Place.model_validate(place) for place in places])
