"""Token wersji danych i ETag kafla.

Jednostki chodza na atrapach (bez bazy). Na koncu sa dwa testy na prawdziwej bazie: pilnuja, ze
migracja 005 zasiala dokladnie jeden wiersz i ze podbicie tokenu naprawde zmienia wartosc. Pisza
w transakcji, ktora jest wycofywana, wiec zaimportowane wojewodztwo zostaje nietkniete.
"""

import os
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest

from app import dataversion
from app.config import Settings
from app.dataversion import (
    TILE_SCHEMA_VERSION,
    DataVersion,
    bump_version,
    etag_matches,
    new_token,
    read_token,
    tile_etag,
    version_for,
)
from tests.conftest import FakePool

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
requires_database = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL nie jest ustawiony")

TILE = (14, 9000, 5500)


class FakeSyncCursor:
    """Kursor psycopg jest kontekstem, wiec atrapa tez musi nim byc."""

    def __init__(self, calls: list[tuple[str, Any]]) -> None:
        self.calls = calls

    def __enter__(self) -> "FakeSyncCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.calls.append((sql, params))


class FakeSyncConnection:
    """Polaczenie do importu: zapisuje wykonane polecenia i nigdy nie commituje."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def cursor(self) -> FakeSyncCursor:
        return FakeSyncCursor(self.calls)


class Clock:
    """Wstrzykiwany zegar — wygasniecie cache'a sprawdzamy bez `sleep`."""

    def __init__(self, now_s: float = 1000.0) -> None:
        self.now_s = now_s

    def __call__(self) -> float:
        return self.now_s

    def advance(self, seconds: float) -> None:
        self.now_s += seconds


def test_every_token_is_different() -> None:
    # Token nie moze zalezec od tego, czy dane sie roznia: ponowny import tego samego pliku
    # nadaje budynkom inne identyfikatory, a tresc snapshotu jest ta sama.
    assert len({new_token() for _ in range(100)}) == 100


def test_etag_joins_the_schema_version_the_token_and_the_tile_coordinates() -> None:
    # Slaby walidator (`W/`), bo ST_AsMVT bez ORDER BY nie gwarantuje tych samych bajtow przy tych
    # samych danych (zmierzone: 45 034 vs 44 979 bajtow dla jednego kafla). Obiecujemy tresc, nie bajty.
    assert tile_etag("abc", *TILE) == f'W/"v{TILE_SCHEMA_VERSION}-abc-14-9000-5500"'


def test_the_tile_schema_version_is_past_the_identifiers_from_the_sequence() -> None:
    # 1 to kafle z kluczem z sekwencji; identyfikator obiektu to dzis osm_id, wiec minimum to 2.
    assert TILE_SCHEMA_VERSION >= 2


def test_bumping_the_tile_schema_version_changes_the_etag_of_the_same_tile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warunek, bez ktorego zmiana tresci kafla jest niebezpieczna.

    Token wersji danych zmienia sie przy imporcie, a przejscie na inny identyfikator obiektu to
    zmiana KODU przy niezmienionych danych. Bez skladnika schematu przegladarka potwierdzilaby
    swiezosc kafla ze starymi identyfikatorami i klik w budynek znowu konczylby sie 404.
    """
    before = tile_etag("ten-sam-token", *TILE)

    monkeypatch.setattr(dataversion, "TILE_SCHEMA_VERSION", TILE_SCHEMA_VERSION + 1)
    after = tile_etag("ten-sam-token", *TILE)

    assert before != after
    assert not etag_matches(before, after)  # stary walidator nie moze dac 304


def test_the_same_tile_and_token_give_the_same_etag() -> None:
    assert tile_etag("abc", *TILE) == tile_etag("abc", *TILE)


def test_different_tiles_have_different_etags() -> None:
    # Bez wspolrzednych w ETagu dwa rozne kafle potwierdzalyby sobie swiezosc nawzajem.
    assert tile_etag("abc", 14, 9000, 5500) != tile_etag("abc", 14, 9001, 5500)
    assert tile_etag("abc", 14, 9000, 5500) != tile_etag("abc", 14, 9000, 5501)
    assert tile_etag("abc", 14, 9000, 5500) != tile_etag("abc", 15, 9000, 5500)


def test_a_new_token_changes_the_etag_of_the_same_tile() -> None:
    # Sedno naprawy: po imporcie ten sam kafel ma inny ETag, wiec stara kopia w przegladarce
    # nie moze zostac potwierdzona jako swieza.
    assert tile_etag("stary", *TILE) != tile_etag("nowy", *TILE)


def test_no_token_means_no_etag() -> None:
    assert tile_etag(None, *TILE) is None
    assert tile_etag("", *TILE) is None


def test_matching_etag_is_recognised() -> None:
    etag = tile_etag("abc", *TILE)
    assert etag_matches(etag, etag)


def test_weak_prefix_and_lists_are_understood() -> None:
    # Klient oddaje ETag doslownie, ale prefiks `W/` i lista wartosci to jego prawo (RFC 9110).
    strong = '"abc-14-9000-5500"'
    assert etag_matches(f"W/{strong}", strong)
    assert etag_matches(strong, f"W/{strong}")
    assert etag_matches(f'"inny", W/{strong}', f"W/{strong}")


def test_a_stale_or_missing_header_does_not_match() -> None:
    etag = tile_etag("nowy", *TILE)
    assert not etag_matches(tile_etag("stary", *TILE), etag)
    assert not etag_matches(None, etag)
    assert not etag_matches("", etag)
    # Gwiazdka znaczy „jesli kafel istnieje" — bez zapytania do PostGIS-a tego nie wiemy.
    assert not etag_matches("*", etag)


def test_nothing_matches_when_there_is_no_etag() -> None:
    assert not etag_matches('"cokolwiek"', None)


async def test_read_token_returns_the_value_from_the_database() -> None:
    assert await read_token(FakePool(row=("abc123",)), 1.0) == "abc123"


async def test_a_missing_version_row_is_not_an_error() -> None:
    # Baza bez migracji 005 albo skasowany wiersz: kafel ma sie narysowac, tylko bez ETagu.
    assert await read_token(FakePool(row=None), 1.0) is None
    assert await read_token(FakePool(row=(None,)), 1.0) is None


async def test_a_dead_database_does_not_raise_from_the_token_read() -> None:
    assert await read_token(FakePool(error=OSError("connection refused")), 1.0) is None


async def test_the_token_is_read_once_for_two_consecutive_requests() -> None:
    pool = FakePool(row=("abc123",))
    version = DataVersion(ttl_s=5.0, clock=Clock())

    first = await version.token(pool, 1.0)
    second = await version.token(pool, 1.0)

    assert (first, second) == ("abc123", "abc123")
    assert pool.timeouts == [1.0]  # drugie zadanie nie dotknelo puli


async def test_an_expired_entry_is_read_again() -> None:
    pool = FakePool(row=("abc123",))
    clock = Clock()
    version = DataVersion(ttl_s=5.0, clock=clock)

    await version.token(pool, 1.0)
    clock.advance(5.0)
    await version.token(pool, 1.0)  # dokladnie na granicy wpis jeszcze obowiazuje
    assert pool.timeouts == [1.0]

    clock.advance(0.001)
    await version.token(pool, 1.0)
    assert pool.timeouts == [1.0, 1.0]


async def test_a_failed_read_is_cached_too() -> None:
    # Przy padnietej bazie nie ma sensu pytac o token przy kazdym z kilkudziesieciu kafli.
    pool = FakePool(error=OSError("connection refused"))
    version = DataVersion(ttl_s=5.0, clock=Clock())

    assert await version.token(pool, 1.0) is None
    assert await version.token(pool, 1.0) is None
    assert pool.timeouts == [1.0]


def test_bump_writes_the_returned_token_without_committing() -> None:
    connection = FakeSyncConnection()

    token = bump_version(connection)

    assert len(connection.calls) == 1
    sql, params = connection.calls[0]
    assert "data_version" in sql
    assert params == {"token": token}


def test_bump_gives_a_different_token_than_before() -> None:
    connection = FakeSyncConnection()

    before = bump_version(connection)
    after = bump_version(connection)

    assert before != after


def test_version_for_keeps_one_instance_per_app() -> None:
    app = SimpleNamespace(state=SimpleNamespace(settings=Settings(data_version_ttl_s=7.0)))

    version = version_for(app)

    assert version_for(app) is version
    assert version.ttl_s == 7.0


@pytest.fixture
def connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(str(DATABASE_URL)) as handle:
        yield handle
        handle.rollback()


@requires_database
def test_migration_seeded_exactly_one_version_row(connection: psycopg.Connection) -> None:
    row = connection.execute("SELECT count(*), max(length(token)) FROM data_version").fetchone()

    assert row is not None
    assert row[0] == 1
    assert row[1] and row[1] > 0


@requires_database
def test_bump_changes_the_token_in_the_database(connection: psycopg.Connection) -> None:
    before = connection.execute("SELECT token FROM data_version WHERE only_row").fetchone()

    token = bump_version(connection)
    after = connection.execute("SELECT token, updated_at FROM data_version WHERE only_row").fetchone()

    assert before is not None and after is not None
    assert after[0] == token
    assert after[0] != before[0]
    connection.rollback()  # nie zostawiamy w bazie tokenu z testu


@requires_database
def test_the_table_cannot_hold_a_second_version(connection: psycopg.Connection) -> None:
    # Singleton jest pilnowany przez schemat, nie przez dyscypline wywolujacych.
    with pytest.raises(psycopg.errors.DatabaseError):
        connection.execute("INSERT INTO data_version (only_row, token) VALUES (false, 'drugi')")
    connection.rollback()
