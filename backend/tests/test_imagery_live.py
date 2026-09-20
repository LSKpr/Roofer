"""Jeden prawdziwy kafel z WMS-a GUGiK. Domyslnie pomijany — sieciowy test nie moze byc
warunkiem zielonego drzewa, a regulamin uslugi zabrania masowego pobierania, wiec tu jest
dokladnie jedno zapytanie, bez petli.

Uruchomienie: IMAGERY_LIVE_TEST=1 .venv/Scripts/python.exe -m pytest tests/test_imagery_live.py
"""

import os

import pytest

from app.config import Settings
from app.imagery import PNG_MAGIC, ImageryClient

pytestmark = pytest.mark.skipif(
    os.environ.get("IMAGERY_LIVE_TEST") != "1",
    reason="Ustaw IMAGERY_LIVE_TEST=1, zeby odpytac prawdziwy WMS GUGiK.",
)

# Kafel nad centrum Warszawy w siatce XYZ (z/x/y) — tam ortofoto jest na pewno.
WARSAW_TILE = (18, 146372, 86317)


async def test_gugik_serves_a_real_png_tile_over_warsaw() -> None:
    client = ImageryClient.from_settings(Settings())
    try:
        payload = await client.tile(*WARSAW_TILE)
    finally:
        await client.aclose()

    assert payload.startswith(PNG_MAGIC)
    # Pusty kafel GUGiK ma okolo 800-1400 B, wiec to jest sprawdzenie, ze przyszlo zdjecie.
    assert len(payload) > 5_000
