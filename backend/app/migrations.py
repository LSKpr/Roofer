import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    name       text PRIMARY KEY,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def load(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    if not directory.is_dir():
        raise MigrationError(f"Katalog migracji nie istnieje: {directory}")
    files = sorted(directory.glob("*.sql"), key=lambda path: path.name)
    if not files:
        raise MigrationError(f"Katalog migracji jest pusty: {directory}")
    return [Migration(path.name, path.read_text(encoding="utf-8")) for path in files]


def pending(available: Sequence[Migration], applied: Mapping[str, str]) -> list[Migration]:
    """Migracje jeszcze niezastosowane. Zmieniona tresc zastosowanego pliku to blad, nie ostrzezenie."""
    for migration in available:
        recorded = applied.get(migration.name)
        if recorded is not None and recorded != migration.checksum:
            raise MigrationError(
                f"Migracja {migration.name} zostala zastosowana z inna trescia. "
                "Nie edytuj zastosowanych plikow — dodaj nowa migracje."
            )
    return [migration for migration in available if migration.name not in applied]


def read_applied(connection: Any) -> dict[str, str]:
    connection.execute(CREATE_TABLE_SQL)
    rows = connection.execute("SELECT name, checksum FROM schema_migrations").fetchall()
    return {name: checksum for name, checksum in rows}


def apply(connection: Any, migrations: Sequence[Migration]) -> list[str]:
    for migration in migrations:
        connection.execute(migration.sql)
        connection.execute(
            "INSERT INTO schema_migrations (name, checksum) VALUES (%s, %s)",
            (migration.name, migration.checksum),
        )
        connection.commit()
    return [migration.name for migration in migrations]
