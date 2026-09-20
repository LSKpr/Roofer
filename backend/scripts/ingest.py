"""Import snapshotow GeoJSON do PostGIS i dopasowanie budynkow do rejestru.

python -m scripts.ingest --registry <plik> --buildings <plik>
python -m scripts.ingest --buildings <plik> --limit 50000   # kalibracja na probce
python -m scripts.ingest --match                            # tylko przeliczenie dopasowan
"""

import argparse
import sys
import time
from collections.abc import Iterator
from itertools import islice
from pathlib import Path

import psycopg

from app.config import get_settings
from app.ingest import DATASETS, IngestReport, MatchReport, analyze, cleanup_staging, ingest, match
from app.snapshots import SnapshotError, iter_features, parse_header


def features_of(path: Path, limit: int | None) -> Iterator[str]:
    with path.open(encoding="utf-8") as handle:
        header = parse_header(handle.readline())
        print(f"  zrodlo: {header.get('source', 'nieznane')}")
        print(f"  wygenerowano: {header.get('generatedAt', 'nieznane')}")
        handle.seek(0)
        features = iter_features(handle)
        yield from islice(features, limit) if limit is not None else features


def report_ingest(report: IngestReport, seconds: float) -> None:
    print(f"  wczytane linie:      {report.staged:>9}")
    print(f"  wstawione obiekty:   {report.inserted:>9}")
    print(f"  naprawiona geometria:{report.repaired:>9}")
    print(f"  bez geometrii:       {report.unparsable:>9}")
    print(f"  puste po naprawie:   {report.empty_after_repair:>9}")
    print(f"  poza Polska:         {report.outside_poland:>9}")
    print(f"  odrzucone razem:     {report.rejected:>9}")
    print(f"  czas:                {seconds:>9.1f} s")


def report_match(report: MatchReport, seconds: float) -> None:
    print(f"  przecinajace sie pary:      {report.pairs:>9}")
    print(f"  pary spelniajace regule:    {report.qualifying_pairs:>9}")
    print(f"  budynki z dopasowaniem:     {report.buildings_with_match:>9}")
    print(f"  czas:                       {seconds:>9.1f} s")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, help="snapshot rejestru GeoAzbest")
    parser.add_argument("--buildings", type=Path, help="snapshot budynkow OSM")
    parser.add_argument("--limit", type=int, help="wczytaj tylko tyle pierwszych obiektow")
    parser.add_argument("--match", action="store_true", help="przelicz dopasowania po imporcie")
    parser.add_argument("--no-match", action="store_true", help="pomin dopasowania")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    jobs = [(DATASETS[name], getattr(args, name)) for name in ("registry", "buildings") if getattr(args, name)]
    if not jobs and not args.match:
        print("Podaj --registry, --buildings albo --match.", file=sys.stderr)
        return 2

    settings = get_settings()
    try:
        with psycopg.connect(settings.database_url) as connection:
            for dataset, path in jobs:
                if not path.is_file():
                    print(f"Nie ma pliku: {path}", file=sys.stderr)
                    return 1
                print(f"{dataset.label} <- {path.name}")
                started = time.perf_counter()
                report = ingest(
                    connection,
                    dataset,
                    features_of(path, args.limit),
                    progress=lambda staged: print(f"  ... {staged} linii", flush=True),
                )
                analyze(connection, dataset.table)
                cleanup_staging(connection)
                connection.commit()
                report_ingest(report, time.perf_counter() - started)

            if args.match or (jobs and not args.no_match):
                print("dopasowanie budynek <-> rejestr")
                started = time.perf_counter()
                result = match(connection)
                analyze(connection, "building_registry_match", "osm_buildings")
                connection.commit()
                report_match(result, time.perf_counter() - started)
    except SnapshotError as error:
        print(f"Snapshot jest niepoprawny: {error}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as error:
        print(f"Brak polaczenia z baza: {error}".strip(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
