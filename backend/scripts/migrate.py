"""Stosuje db/migrations/*.sql w kolejnosci nazw i zapisuje je w schema_migrations."""

import sys

import psycopg

from app.config import get_settings
from app.migrations import MigrationError, apply, load, pending, read_applied


def main() -> int:
    settings = get_settings()
    try:
        with psycopg.connect(settings.database_url) as connection:
            applied = read_applied(connection)
            connection.commit()
            todo = pending(load(), applied)
            if not todo:
                print(f"Baza jest aktualna (zastosowanych migracji: {len(applied)}).")
                return 0
            for name in apply(connection, todo):
                print(f"zastosowano {name}")
    except psycopg.OperationalError as error:
        print(f"Brak polaczenia z baza: {error}".strip(), file=sys.stderr)
        print("Czy `docker compose up -d` wstalo i czy DATABASE_URL wskazuje na port 5433?", file=sys.stderr)
        return 1
    except MigrationError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
