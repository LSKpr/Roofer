"""Proxy do ortofotomapy GUGiK: podklad mapy i wycinek dachu.

Proxy, a nie bezposrednie odpytywanie z przegladarki, bo dopiero tutaj mozemy ograniczyc liczbe
jednoczesnych zapytan do cudzej uslugi, trzymac cache i zamienic ServiceException w XML na 503.

Wycinek dachu ma dwa zrodla i **z dysku wygrywa z WMS-em**: dla 801 budynkow z dwoch wsi mamy gotowy
kadr GUGiK przy 5 cm na piksel (`app/localcrops.py`), dla wszystkich pozostalych liczymy kadr z WMS-a
przy 25 cm. Ktore zrodlo poszlo, mowi pole `roofImage` w `/api/buildings/{osm_id}` — bez tego podpis
w karcie budynku bylby nieprawdziwy dla jednego z dwoch kadrow.
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
from app.localcrops import index_for, read_crop
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
    calkowita, bo walidacje robi FastAPI; do SQL-a idzie rzutowana na text (patrz app/imagery.py).

    Kadr z dysku, gdy go mamy: ten sam adres, ten sam typ MIME i te same naglowki cache, ale
    **parametr `size` dotyczy wtedy wylacznie kadru z WMS-a**. Plik z eksportu ma 256 x 256 i oddajemy
    go bajt w bajt, bo w backendzie nie ma biblioteki do skalowania obrazow (i nie ma jej dodawac —
    front pokazuje kadr w ramce o stalej proporcji, wiec przeglada sie to samo). To jest rzeczywista
    roznica w zachowaniu tego adresu, a nie szczegol implementacji: `?size=1024` na budynku z eksportu
    oddaje 256 px.

    Kadru z dysku nie sprawdzamy w bazie: plik jest zaadresowany tym samym `osm_id`, wiec zapytanie
    o obwiednie budynku byloby tu praca bez wyniku (siatka miniatur otwiera 25 takich zadan naraz).
    """
    crop = index_for(request.app).find(osm_id)
    if crop is not None:
        payload = read_crop(crop)
        if payload is not None:
            return Response(content=payload, media_type=IMAGE_MEDIA_TYPE, headers=CACHE_HEADERS)
        # Plik zniknal albo nie jest PNG-iem po wczytaniu indeksu: lepiej pokazac kadr z WMS-a niz nic.

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
