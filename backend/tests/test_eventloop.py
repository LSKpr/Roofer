import asyncio

from app.eventloop import new_event_loop


def test_loop_supports_add_reader_which_psycopg_needs() -> None:
    loop = new_event_loop()
    try:
        assert not isinstance(loop, getattr(asyncio, "ProactorEventLoop", ()))
        assert hasattr(loop, "add_reader")
    finally:
        loop.close()
