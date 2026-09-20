from __future__ import annotations

import asyncio
import math
import time
from collections import OrderedDict
from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError

from Data.build_roof_dataset import GOOGLE_TILE_URL, TILE_SIZE, world_pixel

from .settings import Settings


class ImageryError(RuntimeError):
    pass


class SatelliteTiles:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.tile_timeout),
            limits=httpx.Limits(max_connections=settings.tile_concurrency, max_keepalive_connections=settings.tile_concurrency),
            follow_redirects=False,
            headers={"User-Agent": "RooferBackend/1.0"},
        )
        self.semaphore = asyncio.Semaphore(settings.tile_concurrency)
        self.cache = OrderedDict()
        self.cache_size = 0
        self.pending: dict[tuple[int, int], asyncio.Task] = {}

    @staticmethod
    def decode(data: bytes) -> Image.Image:
        try:
            with Image.open(BytesIO(data)) as image:
                if image.size != (TILE_SIZE, TILE_SIZE):
                    raise ImageryError("INVALID_TILE_SIZE")
                return image.convert("RGB")
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            raise ImageryError("INVALID_TILE_IMAGE") from error

    async def _download(self, key: tuple[int, int]) -> bytes:
        try:
            for attempt in range(2):
                try:
                    async with self.semaphore:
                        async with self.client.stream("GET", GOOGLE_TILE_URL, params={"lyrs": "s", "z": 20, "x": key[0], "y": key[1]}) as response:
                            response.raise_for_status()
                            data = bytearray()
                            async for chunk in response.aiter_bytes():
                                data.extend(chunk)
                                if len(data) > 2 * 1024 * 1024:
                                    raise ImageryError("TILE_TOO_LARGE")
                    encoded = bytes(data)
                    self.decode(encoded)
                    while self.cache and self.cache_size + len(encoded) > self.settings.tile_cache_bytes:
                        _, (_, previous) = self.cache.popitem(last=False)
                        self.cache_size -= len(previous)
                    if len(encoded) <= self.settings.tile_cache_bytes:
                        self.cache[key] = (time.monotonic(), encoded)
                        self.cache_size += len(encoded)
                    return encoded
                except httpx.HTTPError as error:
                    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in {429, 500, 502, 503, 504}:
                        raise ImageryError("SATELLITE_UNAVAILABLE") from error
                    if attempt == 1:
                        raise ImageryError("SATELLITE_UNAVAILABLE") from error
                    await asyncio.sleep(0.5)
            raise ImageryError("SATELLITE_UNAVAILABLE")
        finally:
            self.pending.pop(key, None)

    async def tile(self, x: int, y: int) -> Image.Image:
        if not 0 <= y < 2**20:
            raise ImageryError("INVALID_TILE_COORDINATES")
        key = (x % (2**20), y)
        cached = self.cache.get(key)
        if cached:
            created, data = cached
            if time.monotonic() - created <= self.settings.tile_cache_ttl:
                self.cache.move_to_end(key)
                return self.decode(data)
            self.cache_size -= len(data)
            del self.cache[key]
        if key not in self.pending:
            task = asyncio.create_task(self._download(key))
            task.add_done_callback(lambda completed: completed.exception() if not completed.cancelled() else None)
            self.pending[key] = task
        return self.decode(await asyncio.shield(self.pending[key]))

    async def crop(self, longitude: float, latitude: float) -> tuple[Image.Image, tuple[int, int]]:
        x, y = world_pixel(longitude, latitude, 20)
        tile_x, tile_y = math.floor(x / TILE_SIZE), math.floor(y / TILE_SIZE)
        positions = [(column, row, tile_x + column - 1, tile_y + row - 1) for row in range(3) for column in range(3)]
        tiles = await asyncio.gather(*(self.tile(tx, ty) for _, _, tx, ty in positions))
        mosaic = Image.new("RGB", (768, 768))
        for (column, row, _, _), tile in zip(positions, tiles, strict=True):
            mosaic.paste(tile, (column * TILE_SIZE, row * TILE_SIZE))
        origin_x, origin_y = (tile_x - 1) * TILE_SIZE, (tile_y - 1) * TILE_SIZE
        left, top = round(x - origin_x - 64), round(y - origin_y - 64)
        return mosaic.crop((left, top, left + 128, top + 128)), (origin_x + left, origin_y + top)

    async def close(self) -> None:
        tasks = list(self.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.client.aclose()
