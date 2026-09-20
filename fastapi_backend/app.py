from __future__ import annotations

import asyncio
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .database import TooManyBuildings
from .schemas import AnalysisMeta, AnalysisResponse, AnalyzeRequest
from .service import AnalysisService
from .settings import Settings


class RequestBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        body = bytearray()
        try:
            async with asyncio.timeout(10):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > 8192:
                        response = JSONResponse({"detail": {"code": "BODY_TOO_LARGE"}}, status_code=413, headers={"Connection": "close"})
                        return await response(scope, receive, send)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            response = JSONResponse({"detail": {"code": "BODY_TIMEOUT"}}, status_code=408, headers={"Connection": "close"})
            return await response(scope, receive, send)
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None, service: AnalysisService | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        token = settings.token_file.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise ValueError("API token must have at least 32 characters; run fastapi_backend.manage create-token")
        app.state.token = token.encode()
        app.state.service = service or AnalysisService(settings)
        app.state.analysis_lock = asyncio.Lock()
        app.state.requests = deque()
        try:
            yield
        finally:
            await app.state.service.close()

    app = FastAPI(
        title="Roofer API", version="1.0.0", lifespan=lifespan,
        description="Building polygons intersecting a WGS84 rectangle with roof asbestos scores. Low-quality or unavailable imagery produces null scores and explicit statuses.",
    )
    app.add_middleware(RequestBodyLimit)
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
        allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Retry-After"],
    )
    bearer = HTTPBearer(auto_error=False)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse(status_code=422, content={"detail": [{key: item[key] for key in ("loc", "msg", "type")} for item in error.errors()]})

    async def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or credentials.scheme.lower() != "bearer" or not secrets.compare_digest(credentials.credentials.encode(), app.state.token):
            raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "Valid Bearer token required"}, headers={"WWW-Authenticate": "Bearer"})

    @app.get("/health")
    async def health():
        current = app.state.service
        return {
            "status": "ok", "model_id": current.model.model_id,
            "database": current.store.info,
            "limits": {"max_buildings": settings.max_buildings, "max_area_km2": settings.max_area_km2, "request_timeout_seconds": settings.request_timeout, "requests_per_minute": settings.requests_per_minute},
        }

    @app.post("/v1/analyze", response_model=AnalysisResponse, dependencies=[Depends(authenticate)], responses={401: {"description": "Missing or invalid token"}, 413: {"description": "Area or building count exceeds limit; nothing is silently truncated"}, 429: {"description": "Busy or rate limited"}, 504: {"description": "Analysis deadline exceeded"}})
    async def analyze(request: AnalyzeRequest):
        if request.area_km2() > settings.max_area_km2:
            raise HTTPException(413, detail={"code": "AREA_TOO_LARGE", "max_area_km2": settings.max_area_km2})
        now = time.monotonic()
        recent = app.state.requests
        while recent and now - recent[0] >= 60:
            recent.popleft()
        if len(recent) >= settings.requests_per_minute:
            raise HTTPException(429, detail={"code": "RATE_LIMITED"}, headers={"Retry-After": str(max(1, int(60 - now + recent[0]) + 1))})
        lock = app.state.analysis_lock
        if lock.locked():
            raise HTTPException(429, detail={"code": "BUSY", "message": "Another analysis is running"}, headers={"Retry-After": "5"})
        recent.append(now)
        current = app.state.service
        try:
            async with lock, asyncio.timeout(settings.request_timeout):
                buildings = await asyncio.to_thread(current.store.query, request.bbox(), settings.max_buildings)
                features = await current.analyze(buildings)
        except TooManyBuildings as error:
            raise HTTPException(413, detail={"code": "TOO_MANY_BUILDINGS", "limit": error.limit, "message": str(error)}) from error
        except TimeoutError as error:
            raise HTTPException(504, detail={"code": "ANALYSIS_TIMEOUT", "message": "Use a smaller rectangle or retry later"}) from error
        return AnalysisResponse(
            bbox=request.bbox(), features=features,
            meta=AnalysisMeta(
                matched=len(features), predicted=sum(feature.properties.status == "ok" for feature in features),
                low_quality=sum(feature.properties.status == "low_quality" for feature in features),
                errors=sum(feature.properties.status in {"imagery_error", "geometry_error"} for feature in features),
                model_id=current.model.model_id, elapsed_seconds=round(time.monotonic() - now, 3),
                building_source=current.store.info["source"],
            ),
        )

    return app


app = create_app()
