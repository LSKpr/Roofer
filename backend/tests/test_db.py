from app.db import first_line, read_status
from tests.conftest import FakePool


async def test_reports_postgis_version_from_database() -> None:
    status = await read_status(FakePool(row=("3.5.1",)), timeout=1.0)

    assert status == type(status)(reachable=True, postgis_version="3.5.1")


async def test_passes_timeout_to_the_pool() -> None:
    pool = FakePool(row=("3.5.1",))

    await read_status(pool, timeout=2.5)

    assert pool.timeouts == [2.5]


async def test_reports_unreachable_database_without_raising() -> None:
    status = await read_status(FakePool(error=OSError("connection refused\nsecond line")), timeout=1.0)

    assert not status.reachable
    assert status.postgis_version is None
    assert status.detail == "connection refused"


async def test_reports_database_without_postgis_as_reachable_but_incomplete() -> None:
    status = await read_status(FakePool(row=None), timeout=1.0)

    assert status.reachable
    assert status.postgis_version is None
    assert "PostGIS" in (status.detail or "")


def test_first_line_falls_back_to_exception_type_when_message_is_empty() -> None:
    assert first_line(TimeoutError()) == "TimeoutError"
