"""Jedyny test dotykajacy prawdziwej bazy. Uruchamia sie tylko z ustawionym TEST_DATABASE_URL."""

import os

import pytest

from app.db import create_pool, read_status

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL nie jest ustawiony")


async def test_postgis_is_installed_in_the_real_database() -> None:
    pool = create_pool(str(DATABASE_URL))
    await pool.open(wait=True)
    try:
        status = await read_status(pool, timeout=5.0)
    finally:
        await pool.close()

    assert status.reachable
    assert status.postgis_version is not None
