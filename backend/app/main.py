from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db import Pool, create_pool
from app.routes import area, buildings, geocode, health, imagery, prediction, tiles


async def close_http_clients(app: FastAPI) -> None:
    """Klienci do GUGiK i Nominatima powstaja leniwie, wiec przy zamknieciu moga nie istniec."""
    client = getattr(app.state, "imagery", None)
    if client is not None:
        await client.aclose()
    geocoder = getattr(app.state, "geocoder", None)
    if geocoder is not None:
        await geocoder.close()
    # Dostawca oceny pokrycia ma klienta tylko wtedy, gdy jest nim HttpModelProvider.
    provider = getattr(app.state, "roof_provider", None)
    close = getattr(provider, "close", None)
    if close is not None:
        await close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool: Pool = app.state.pool_factory(app.state.settings)
    app.state.pool = pool
    await pool.open(wait=False)
    try:
        yield
    finally:
        await close_http_clients(app)
        await pool.close()


def create_app(settings: Settings | None = None, pool_factory: Callable[[Settings], Pool] | None = None) -> FastAPI:
    app = FastAPI(title="Roofer API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings or get_settings()
    app.state.pool_factory = pool_factory or (lambda config: create_pool(config.database_url))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app.state.settings.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    routers = (
        health.router,
        tiles.router,
        buildings.router,
        imagery.router,
        area.router,
        geocode.router,
        prediction.router,
    )
    for router in routers:
        app.include_router(router, prefix="/api")
    return app


app = create_app()
