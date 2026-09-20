"""Czytnik snapshotow GeoJSON zapisanych linia po linii.

Oba snapshoty w Additional_data maja ten sam uklad: pierwsza linia konczy sie na `"features":[`,
kazdy obiekt zajmuje jedna linie i konczy sie przecinkiem (poza ostatnim), a stopka
`],"numberReturned":N}` deklaruje liczbe obiektow. Czytamy je strumieniowo, bo plik budynkow
ma 966 MB, i sprawdzamy zadeklarowana liczbe — inaczej obciety plik zaimportowalby sie po cichu.
"""

import json
from collections.abc import Iterable, Iterator
from typing import Any

FEATURES_MARKER = '"features":['


class SnapshotError(RuntimeError):
    pass


def parse_header(line: str) -> dict[str, Any]:
    """Naglowek bez tablicy obiektow. Domkniecie `]}` robi z niego poprawny JSON."""
    text = line.strip()
    if not text.endswith(FEATURES_MARKER):
        raise SnapshotError(f"Pierwsza linia snapshotu nie konczy sie na {FEATURES_MARKER} — format sie zmienil.")
    try:
        return json.loads(text + "]}")
    except json.JSONDecodeError as error:
        raise SnapshotError("Nie umiem odczytac naglowka snapshotu.") from error


def parse_footer(line: str) -> int | None:
    """Zadeklarowana liczba obiektow albo None, gdy stopka jej nie podaje."""
    text = line.strip()
    if not text.startswith("]"):
        raise SnapshotError(f"Linia zamykajaca snapshotu nie zaczyna sie od ']': {text[:40]}")
    rest = text[1:].lstrip().lstrip(",")
    try:
        footer = {} if rest in ("", "}") else json.loads("{" + rest)
    except json.JSONDecodeError as error:
        raise SnapshotError("Nie umiem odczytac stopki snapshotu — format sie zmienil.") from error
    declared = footer.get("numberReturned")
    if declared is not None and not isinstance(declared, int):
        raise SnapshotError("Snapshot deklaruje numberReturned, ktore nie jest liczba calkowita.")
    return declared


def iter_features(lines: Iterable[str]) -> Iterator[str]:
    """Surowy JSON kolejnych obiektow, bez konczacego przecinka.

    Weryfikacja liczby obiektow dzieje sie po wyczerpaniu pliku, wiec konsument, ktory przerwie
    wczesniej (import z limitem), swiadomie jej nie uruchamia.
    """
    iterator = iter(lines)
    first = next(iterator, None)
    if first is None:
        raise SnapshotError("Snapshot jest pusty.")
    parse_header(first)

    count = 0
    declared: int | None = None
    closed = False
    for line in iterator:
        text = line.strip()
        if not text:
            continue
        if text.startswith("]"):
            declared = parse_footer(text)
            closed = True
            break
        yield text.rstrip(",")
        count += 1

    if not closed:
        raise SnapshotError("Snapshot nie ma linii zamykajacej — plik jest obciety.")
    if declared is not None and declared != count:
        raise SnapshotError(f"Snapshot deklaruje {declared} obiektow, a zawiera {count}.")
