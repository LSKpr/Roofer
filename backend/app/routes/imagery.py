"""Proxy do ortofotomapy GUGiK: podklad mapy i wycinek dachu.

Proxy, a nie bezposrednie odpytywanie z przegladarki, bo dopiero tutaj mozemy ograniczyc liczbe
jednoczesnych zapytan do cudzej uslugi, trzymac cache i zamienic ServiceException w XML na 503.
"""

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.imagery import (
    IMAGE_MEDIA_TYPE,
    ROOF_DEFAULT_SIZE,
    ROOF_MAX_SIZE,
    ROOF_MIN_SIZE,
    ImageryUnavailable,
    client_for,
    read_roof_bbox,
)
from app.tiles import within_grid

router = APIRouter(tags=["imagery"])

# Ortofoto z danego nalotu jest niezmienne, wiec doba w cache przegladarki to i tak ostroznie.
CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}
RESPONSES: dict[int | str, dict[str, object]] = {200: {"content": {IMAGE_MEDIA_TYPE: {}}}, 503: {}}


@router.get("/imagery/orthophoto/{z}/{x}/{y}.png", response_class=Response, responses=RESPONSES)
async def orthophoto_tile(z: int, x: int, y: int, request: Request) -> Response:
    if not within_grid(z, x, y):
        raise HTTPException(status_code=400, detail="Tile coordinates are outside the grid for this zoom.")
    try:
        payload = await client_for(request.app).tile(z, x, y)
    except ImageryUnavailable:  # brak ortofoto zostawia na mapie podklad OSM, a nie pustke
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(content=payload, media_type=IMAGE_MEDIA_TYPE, headers=CACHE_HEADERS)


@router.get("/buildings/{osm_id}/roof.png", response_class=Response, responses=RESPONSES)
async def roof_image(
    osm_id: int,
    request: Request,
    size: int = Query(ROOF_DEFAULT_SIZE, ge=ROOF_MIN_SIZE, le=ROOF_MAX_SIZE),
) -> Response:
    """Budynek wskazuje `osm_id` — ten sam adres, ktory niesie kafel i karta budynku. Liczba
    calkowita, bo walidacje robi FastAPI; do SQL-a idzie rzutowana na text (patrz app/imagery.py)."""
    settings = request.app.state.settings
    try:
        bbox = await read_roof_bbox(request.app.state.pool, osm_id, settings.database_timeout_s)
    except Exception:  # padnieta baza to 503; w znaczniku <img> tresc bledu i tak nikt nie zobaczy
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if bbox is None:
        raise HTTPException(status_code=404, detail="There is no building with this identifier.")

    try:
        payload = await client_for(request.app).roof(bbox, size)
    except ImageryUnavailable:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(content=payload, media_type=IMAGE_MEDIA_TYPE, headers=CACHE_HEADERS)
