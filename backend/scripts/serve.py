"""Serwer developerski. Pętla asyncio jest podana jawnie — patrz app/eventloop.py."""

import uvicorn

from app.config import get_settings

LOOP_FACTORY = "app.eventloop:new_event_loop"


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.api_port,
        reload=True,
        loop=LOOP_FACTORY,  # type: ignore[arg-type]
    )


if __name__ == "__main__":
    main()
