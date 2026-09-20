from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from psycopg_pool import AsyncConnectionPool

POSTGIS_VERSION_SQL = "SELECT extversion FROM pg_extension WHERE extname = 'postgis'"


class Pool(Protocol):
    """Minimalny kontrakt puli, ktory da sie podstawic w testach bez bazy."""

    async def open(self, wait: bool = False) -> None: ...

    async def close(self) -> None: ...

    def connection(self, timeout: float | None = None) -> AbstractAsyncContextManager[Any]: ...


@dataclass(frozen=True)
class DatabaseStatus:
    reachable: bool
    postgis_version: str | None = None
    detail: str | None = None


def create_pool(database_url: str) -> AsyncConnectionPool:
    return AsyncConnectionPool(database_url, min_size=1, max_size=8, open=False)


def first_line(error: BaseException) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


async def read_status(pool: Pool, timeout: float) -> DatabaseStatus:
    try:
        async with pool.connection(timeout=timeout) as connection:
            cursor = await connection.execute(POSTGIS_VERSION_SQL)
            row = await cursor.fetchone()
    except Exception as error:  # sonda zdrowia nie ma prawa wywalic procesu
        return DatabaseStatus(reachable=False, detail=first_line(error))
    if row is None:
        return DatabaseStatus(reachable=True, detail="Baza odpowiada, ale nie ma w niej rozszerzenia PostGIS.")
    return DatabaseStatus(reachable=True, postgis_version=str(row[0]))
