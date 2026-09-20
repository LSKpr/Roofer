from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path

from .database import build_database
from .settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the Roofer backend without overwriting existing assets")
    commands = parser.add_subparsers(dest="command", required=True)
    database = commands.add_parser("build-db")
    database.add_argument("--source", type=Path, required=True)
    database.add_argument("--output", type=Path, default=Settings().database_path)
    token = commands.add_parser("create-token")
    token.add_argument("--output", type=Path, default=Settings().token_file)
    args = parser.parse_args()
    destination = args.output.expanduser().resolve()
    if args.command == "build-db":
        print(json.dumps(build_database(args.source.expanduser(), destination), indent=2))
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(secrets.token_urlsafe(48) + "\n")
        print(f"Token written to {destination}; its value is not printed")


if __name__ == "__main__":
    main()
