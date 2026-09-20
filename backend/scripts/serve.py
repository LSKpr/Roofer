"""Serwer developerski.

Dwie rzeczy sa tu zrobione inaczej, niz podpowiada dokumentacja uvicorna, i obie z powodu:

1. Petla asyncio jest podana jawnie, bo psycopg nie dziala na ProactorEventLoop — patrz
   app/eventloop.py.
2. Nie uzywamy `reload=True` uvicorna. Na tej maszynie wykrywa on zmiane pliku, wypisuje
   "Reloading...", nowy worker nigdy nie wstaje, a stary dalej odpowiada — czyli serwer cicho
   podaje stary kod. `--watch` restartuje caly proces przez watchfiles, co jest sprawdzalne.
"""

import sys
from pathlib import Path

import uvicorn

from app.config import get_settings

LOOP_FACTORY = "app.eventloop:new_event_loop"
WATCHED = Path(__file__).resolve().parents[1] / "app"


def serve() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.api_port,
        loop=LOOP_FACTORY,  # type: ignore[arg-type]
    )


def watch() -> None:
    from watchfiles import PythonFilter, run_process

    # Cel podany sciezka modulowa, a nie komenda: na Windowsie watchfiles dzieli komende
    # shlexem z posix=False, wiec sciezka do pythona w cudzyslowach dotarlaby z cudzyslowami.
    run_process(
        WATCHED,
        target="scripts.serve.serve",
        target_type="function",
        watch_filter=PythonFilter(),
        callback=lambda changes: print(f"zmiana w {len(changes)} plikach — restart serwera"),
    )


def main() -> None:
    watch() if "--watch" in sys.argv[1:] else serve()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(0) from None
