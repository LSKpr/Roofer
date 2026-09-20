from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db import Pool, create_pool
from app.routes import health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool: Pool = app.state.pool_factory(app.state.settings)
    app.state.pool = pool
    await pool.open(wait=False)
    try:
        yield
    finally:
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
    app.include_router(health.router, prefix="/api")
    return app


app = create_app()
