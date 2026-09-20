from fastapi import APIRouter, HTTPException, Request, Response, status

from app.tiles import tile_sql, within_grid

router = APIRouter(tags=["tiles"])

MEDIA_TYPE = "application/vnd.mapbox-vector-tile"
# Dane zmieniaja sie tylko przy imporcie, wiec przegladarka moze trzymac kafle przez godzine.
CACHE_HEADERS = {"Cache-Control": "public, max-age=3600"}


@router.get(
    "/tiles/buildings/{z}/{x}/{y}.mvt",
    response_class=Response,
    responses={200: {"content": {MEDIA_TYPE: {}}}, 204: {}, 503: {}},
)
async def buildings_tile(z: int, x: int, y: int, request: Request) -> Response:
    if not within_grid(z, x, y):
        raise HTTPException(status_code=400, detail="Wspolrzedne kafla sa poza siatka dla tego zoomu.")
    query = tile_sql(z)
    if query is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=CACHE_HEADERS)

    settings = request.app.state.settings
    try:
        async with request.app.state.pool.connection(timeout=settings.database_timeout_s) as connection:
            cursor = await connection.execute(query, {"z": z, "x": x, "y": y})
            row = await cursor.fetchone()
    except Exception:  # padnieta baza nie moze wywalic calej mapy
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    tile = bytes(row[0]) if row and row[0] else b""
    if not tile:
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=CACHE_HEADERS)
    return Response(content=tile, media_type=MEDIA_TYPE, headers=CACHE_HEADERS)
