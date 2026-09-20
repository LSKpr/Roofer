from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

from app.eventloop import new_event_loop


def pytest_asyncio_loop_factories(config: Any, item: Any) -> Mapping[str, Callable[[], Any]]:
    """Testy async dostaja te sama petle co serwer — inaczej psycopg nie polaczy sie na Windowsie."""
    return {"selector": new_event_loop}


class FakeCursor:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self.row = row

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


class FakeConnection:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self.row = row
        self.statements: list[str] = []

    async def execute(self, sql: str, params: Sequence[Any] | None = None) -> FakeCursor:
        self.statements.append(sql)
        return FakeCursor(self.row)


class FakePool:
    """Pula bez bazy: albo oddaje przygotowany wiersz, albo rzuca zadanym bledem."""

    def __init__(self, row: tuple[Any, ...] | None = None, error: BaseException | None = None) -> None:
        self.row = row
        self.error = error
        self.opened = False
        self.closed = False
        self.timeouts: list[float | None] = []

    async def open(self, wait: bool = False) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True

    @asynccontextmanager
    async def connection(self, timeout: float | None = None) -> AsyncIterator[FakeConnection]:
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        yield FakeConnection(self.row)
