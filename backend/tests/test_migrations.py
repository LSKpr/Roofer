from pathlib import Path

import pytest

from app.migrations import Migration, MigrationError, load, pending


def write(directory: Path, name: str, sql: str) -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def test_load_returns_files_sorted_by_name(tmp_path: Path) -> None:
    write(tmp_path, "002_buildings.sql", "SELECT 2")
    write(tmp_path, "001_postgis.sql", "SELECT 1")

    assert [migration.name for migration in load(tmp_path)] == ["001_postgis.sql", "002_buildings.sql"]


def test_load_rejects_an_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="pusty"):
        load(tmp_path)


def test_load_rejects_a_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="nie istnieje"):
        load(tmp_path / "nope")


def test_pending_skips_already_applied_migrations() -> None:
    first = Migration("001_postgis.sql", "SELECT 1")
    second = Migration("002_buildings.sql", "SELECT 2")

    assert pending([first, second], {first.name: first.checksum}) == [second]


def test_pending_rejects_an_edited_migration() -> None:
    migration = Migration("001_postgis.sql", "SELECT 1")

    with pytest.raises(MigrationError, match="inna trescia"):
        pending([migration], {migration.name: "stary-checksum"})
