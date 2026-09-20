from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from app.db import read_status

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    postgis: str | None = None
    detail: str | None = None


@router.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
async def health(request: Request, response: Response) -> HealthResponse:
    settings = request.app.state.settings
    result = await read_status(request.app.state.pool, settings.database_timeout_s)
    if not result.reachable:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", database="unavailable", detail=result.detail)
    if result.postgis_version is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", database="ok", detail=result.detail)
    return HealthResponse(status="ok", database="ok", postgis=result.postgis_version)
