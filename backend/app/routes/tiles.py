from fastapi import APIRouter, HTTPException, Request, Response, status

from app.dataversion import etag_matches, tile_etag, version_for
from app.tiles import tile_sql, within_grid

router = APIRouter(tags=["tiles"])

MEDIA_TYPE = "application/vnd.mapbox-vector-tile"

# `no-cache` znaczy „mozesz trzymac, ale przed uzyciem dopytaj", a nie „nie cachuj". Kafel zostaje
# w cache przegladarki, tylko o jego swiezosci decyduje ETag, a nie zgadniety czas zycia. Poprzednie
# `max-age=3600` dawalo po imporcie godzine kafli ze starymi identyfikatorami budynkow i klik
# w budynek konczyl sie 404 (patrz app/dataversion.py).
#
# Uwaga dla kazdej przyszlej zmiany w app/tiles.py: ETag pilnuje wersji danych ORAZ wersji schematu
# kafla. Inna tresc albo inne znaczenie kafla przy tych samych danych wymaga podbicia
# TILE_SCHEMA_VERSION, inaczej przegladarka oddaje 304 na kafel, ktorego kod juz nie umie czytac.
CACHE_HEADERS = {"Cache-Control": "no-cache"}

# Bez tokenu wersji (brak wiersza w bazie, padnieta baza) nie umiemy potwierdzic swiezosci kafla,
# wiec nie wolno pozwolic go trzymac: `no-store` kosztuje ruch, ale nie da sie na nim oprzec starych
# identyfikatorow. Mapa dziala dalej — tylko bez cache'a.
NO_STORE_HEADERS = {"Cache-Control": "no-store"}


def cache_headers(etag: str | None) -> dict[str, str]:
    return {**CACHE_HEADERS, "ETag": etag} if etag else dict(NO_STORE_HEADERS)


@router.get(
    "/tiles/buildings/{z}/{x}/{y}.mvt",
    response_class=Response,
    responses={200: {"content": {MEDIA_TYPE: {}}}, 204: {}, 304: {}, 503: {}},
)
async def buildings_tile(z: int, x: int, y: int, request: Request) -> Response:
    if not within_grid(z, x, y):
        raise HTTPException(status_code=400, detail="Tile coordinates are outside the grid for this zoom.")
    query = tile_sql(z)
    if query is None:
        # Ponizej progu zoomu kafel jest pusty z decyzji w kodzie, nie z powodu danych, wiec nie
        # pytamy nawet o token wersji. Rewalidacja 204 jest darmowa, a ETag nic by tu nie oszczedzil.
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=CACHE_HEADERS)

    settings = request.app.state.settings
    pool = request.app.state.pool
    token = await version_for(request.app).token(pool, settings.database_timeout_s)
    etag = tile_etag(token, z, x, y)
    headers = cache_headers(etag)

    if etag_matches(request.headers.get("if-none-match"), etag):
        # 304 przed zapytaniem do PostGIS-a — w tym jest caly zysk: nie generujemy kafla, ktory
        # klient juz ma. Odpowiedz nie moze miec ciala ani Content-Type, dlatego bez `media_type`.
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    try:
        async with pool.connection(timeout=settings.database_timeout_s) as connection:
            cursor = await connection.execute(query, {"z": z, "x": x, "y": y})
            row = await cursor.fetchone()
    except Exception:  # padnieta baza nie moze wywalic calej mapy
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    tile = bytes(row[0]) if row and row[0] else b""
    if not tile:
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)
    return Response(content=tile, media_type=MEDIA_TYPE, headers=headers)
