import asyncio
import sys


def new_event_loop() -> asyncio.AbstractEventLoop:
    """Pętla, na której psycopg dziala.

    Domyslna petla asyncio na Windowsie to ProactorEventLoop, ktora nie ma `add_reader`,
    wiec psycopg w trybie async nie potrafi na niej otworzyc polaczenia. Uzywamy jej
    zarowno w uvicornie (`--loop app.eventloop:new_event_loop`), jak i w testach.
    """
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()
