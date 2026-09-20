import asyncio
import csv
import io
import logging
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from geoalchemy2.shape import to_shape
from shapely.geometry import box
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import AnalysisJob, AnalysisJobBuilding, Building, BuildingRegistryMatch, ModelPrediction, RegistryFeature, RegistrySyncCheckpoint
from app.providers.geoazbest import GeoAzbestUnavailable, GeoAzbestWfsClient, WFS_LAYERS, synchronize_layer
from app.providers.imagery import GUGIK_WMS_CURRENT, GUGIK_WMS_CURRENT_DETAIL, GUGIK_WMS_TIME, GUGIK_WMS_TIME_DETAIL, ImageryDescriptor, build_imagery_provider, tile_request_candidates
from app.schemas import AnalysisJobResponse, AnalysisRequest, BuildingDetail, GeocodeResult, ImageryLayerResponse, ModelPredictionResponse, RegistryEvidence, ReviewRequest, StatisticsResponse, SyncRequest, SyncResponse
from app.services.analysis import AnalysisValidationError, create_analysis_job, run_analysis_job
from app.services.geo import geojson_mapping
from app.services.matching import RegistryCandidate, aggregate_status

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("roofer.api")
TILE_CACHE_LIMIT = 768
tile_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
tile_semaphore = asyncio.Semaphore(4)
tile_clients: dict[str, httpx.AsyncClient] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    tile_clients["imagery"] = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.external_timeout_seconds, connect=10.0),
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=8, keepalive_expiry=60.0),
        headers={"User-Agent": "Roofer/0.1 viewport imagery client"},
    )
    try:
        yield
    finally:
        await tile_clients.pop("imagery").aclose()


app = FastAPI(title="Roofer API", version="0.1.0", openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


async def fetch_imagery_tile(candidates: list[tuple[str, dict[str, str]]]) -> tuple[bytes, str]:
    client = tile_clients.get("imagery")
    if client is None:
        raise HTTPException(503, {"status": "source_unavailable", "detail": "Imagery client is not initialised"})
    last_error: Exception | None = None
    async with tile_semaphore:
        for url, params in candidates:
            for attempt in range(2):
                try:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if not content_type.startswith("image/"):
                        raise ValueError(f"non-image response: {content_type or 'unknown content type'}")
                    return response.content, content_type
                except (httpx.HTTPError, ValueError) as error:
                    last_error = error
                    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 404:
                        break
                    if attempt == 0:
                        await asyncio.sleep(0.3)
    logger.info("No official GUGiK imagery available for tile: %s", last_error)
    raise HTTPException(503, {"status": "source_unavailable", "detail": str(last_error)})


@app.get("/api/v1/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(select(1))
    return {"status": "ok"}


def job_or_404(db: Session, job_id: UUID) -> AnalysisJob:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(404, "Analysis job not found")
    return job


@app.post("/api/v1/analysis-jobs", response_model=AnalysisJobResponse, status_code=202)
def create_job(request: AnalysisRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> AnalysisJob:
    try:
        job = create_analysis_job(db, request.geometry, request.requested_years, settings)
    except AnalysisValidationError as error:
        raise HTTPException(422, str(error)) from error
    background_tasks.add_task(run_analysis_job, SessionLocal, job.id, settings)
    return job


@app.get("/api/v1/analysis-jobs/{job_id}", response_model=AnalysisJobResponse)
def get_job(job_id: UUID, db: Session = Depends(get_db)) -> AnalysisJob:
    return job_or_404(db, job_id)


def evidence_for(match: BuildingRegistryMatch) -> RegistryEvidence:
    feature = match.registry_feature
    return RegistryEvidence(
        match_id=match.id,
        source_feature_id=feature.source_feature_id,
        source_layer=feature.geoazbest_layer,
        status=feature.registry_status,
        location_id=feature.location_id,
        parcel_number=feature.parcel_number,
        teryt=feature.teryt,
        urgency=feature.urgency,
        planned_removal_year=feature.planned_removal_year,
        actual_removal_year=feature.actual_removal_year,
        inventory_amount=feature.inventory_amount,
        disposed_amount=feature.disposed_amount,
        synchronized_at=feature.synchronized_at,
        match_method=match.match_method,
        intersection_area_m2=match.intersection_area_m2,
        overlap_ratio=match.overlap_ratio,
        confidence=match.confidence,
        ambiguous=match.ambiguity_flag,
        manually_reviewed=match.manual_reviewed,
    )


def warning_for(status: str, source_status: str, evidence: list[RegistryEvidence]) -> list[str]:
    warnings = ["Registry status is not laboratory confirmation of a roof material."]
    if status == "not_listed":
        warnings.append("Not listed in the registry. Absence from GeoAzbest is not evidence that a roof is asbestos-free.")
    if status == "unknown" or source_status == "source_unavailable":
        warnings.append("Official registry availability is unknown for this analysis. No negative inference is made.")
    if source_status == "demo_fixture":
        warnings.append("This result uses the deterministic demo fixture because a live external source was unavailable.")
    if any(item.actual_removal_year for item in evidence):
        warnings.append("A removal record can refer to siding, pipes, stored material, or part of a roof; imagery comparison is historical inference only.")
    return warnings


def building_feature(building: Building, status: str, source_status: str, before_after: bool) -> dict[str, Any]:
    evidence = [evidence_for(match) for match in building.matches]
    return {
        "type": "Feature",
        "id": str(building.id),
        "geometry": geojson_mapping(to_shape(building.geometry)),
        "properties": {
            "id": str(building.id),
            "status": status,
            "source_provider": building.source_provider,
            "source_object_type": building.source_object_type,
            "source_object_id": building.source_object_id,
            "osm_tags": building.osm_tags,
            "match_confidence": max((evidence_item.confidence for evidence_item in evidence), default=None),
            "has_before_after_imagery": before_after,
            "manual_reviewed": bool(evidence) and all(evidence_item.manually_reviewed for evidence_item in evidence),
            "registry_source_status": source_status,
        },
    }


def filtered_job_features(db: Session, job_id: UUID, statuses: set[str] | None = None, removal_year_min: int | None = None, removal_year_max: int | None = None, urgency: str | None = None, minimum_confidence: float | None = None, before_after_only: bool = False, reviewed: bool | None = None) -> list[dict[str, Any]]:
    rows = db.execute(
        select(AnalysisJobBuilding, Building)
        .join(Building, Building.id == AnalysisJobBuilding.building_id)
        .options(selectinload(Building.matches).selectinload(BuildingRegistryMatch.registry_feature))
        .where(AnalysisJobBuilding.analysis_job_id == job_id)
    ).all()
    features = []
    for result, building in rows:
        evidence = [evidence_for(match) for match in building.matches]
        confidence = max((item.confidence for item in evidence), default=0.0)
        manual = bool(evidence) and all(item.manually_reviewed for item in evidence)
        removal_years = [item.actual_removal_year for item in evidence if item.actual_removal_year is not None]
        if statuses and result.status not in statuses:
            continue
        if removal_year_min is not None and not any(year >= removal_year_min for year in removal_years):
            continue
        if removal_year_max is not None and not any(year <= removal_year_max for year in removal_years):
            continue
        if urgency and not any(item.urgency == urgency for item in evidence):
            continue
        if minimum_confidence is not None and confidence < minimum_confidence:
            continue
        if before_after_only and not result.has_before_after_imagery:
            continue
        if reviewed is not None and manual != reviewed:
            continue
        features.append(building_feature(building, result.status, result.registry_source_status, result.has_before_after_imagery))
    return features


@app.get("/api/v1/analysis-jobs/{job_id}/buildings")
def get_job_buildings(job_id: UUID, status: str | None = None, removal_year_min: int | None = None, removal_year_max: int | None = None, urgency: str | None = None, minimum_confidence: float | None = Query(default=None, ge=0, le=1), before_after_only: bool = False, reviewed: bool | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    job_or_404(db, job_id)
    statuses = set(status.split(",")) if status else None
    return {"type": "FeatureCollection", "features": filtered_job_features(db, job_id, statuses, removal_year_min, removal_year_max, urgency, minimum_confidence, before_after_only, reviewed)}


@app.get("/api/v1/buildings")
def get_buildings(bbox: str = Query(pattern=r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?$"), db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        min_lon, min_lat, max_lon, max_lat = map(float, bbox.split(","))
        if min_lon >= max_lon or min_lat >= max_lat:
            raise ValueError
    except ValueError as error:
        raise HTTPException(422, "Invalid bounding box") from error
    envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
    buildings = db.scalars(select(Building).options(selectinload(Building.matches).selectinload(BuildingRegistryMatch.registry_feature)).where(func.ST_Intersects(Building.geometry, envelope))).all()
    features = []
    for building in buildings:
        candidates = {str(match.registry_feature_id): RegistryCandidate(str(match.registry_feature_id), to_shape(match.registry_feature.geometry), match.registry_feature.location_id, match.registry_feature.parcel_number, match.registry_feature.registry_status) for match in building.matches}
        decisions = []
        status = aggregate_status(decisions, candidates, True) if not candidates else ("ambiguous" if any(match.ambiguity_flag for match in building.matches) else "listed" if any(match.registry_feature.registry_status == "listed" for match in building.matches) else "cleaned" if any(match.registry_feature.registry_status == "cleaned" for match in building.matches) else "unknown")
        features.append(building_feature(building, status, "available", False))
    return {"type": "FeatureCollection", "features": features}


@app.get("/api/v1/buildings/{building_id}", response_model=BuildingDetail)
def get_building(building_id: UUID, job_id: UUID | None = None, selected_imagery_year: int | None = None, db: Session = Depends(get_db)) -> BuildingDetail:
    building = db.scalar(select(Building).options(selectinload(Building.matches).selectinload(BuildingRegistryMatch.registry_feature)).where(Building.id == building_id))
    if building is None:
        raise HTTPException(404, "Building not found")
    source_status = "available"
    status = "not_listed"
    if job_id:
        result = db.scalar(select(AnalysisJobBuilding).where(AnalysisJobBuilding.analysis_job_id == job_id, AnalysisJobBuilding.building_id == building_id))
        if result:
            status, source_status = result.status, result.registry_source_status
    elif building.matches:
        status = "ambiguous" if any(match.ambiguity_flag for match in building.matches) else "listed" if any(match.registry_feature.registry_status == "listed" for match in building.matches) else "cleaned" if any(match.registry_feature.registry_status == "cleaned" for match in building.matches) else "unknown"
    evidence = [evidence_for(match) for match in building.matches]
    latest_registry = max((item.synchronized_at for item in evidence), default=None)
    return BuildingDetail(id=building.id, status=status, geometry=geojson_mapping(to_shape(building.geometry)), source_provider=building.source_provider, source_object_type=building.source_object_type, source_object_id=building.source_object_id, osm_tags=building.osm_tags, evidence=evidence, warnings=warning_for(status, source_status, evidence), selected_imagery_year=selected_imagery_year, data_source_timestamps={"building_imported_at": building.imported_at.isoformat() if building.imported_at else None, "registry_synchronized_at": latest_registry.isoformat() if latest_registry else None})


@app.get("/api/v1/buildings/{building_id}/predictions", response_model=list[ModelPredictionResponse])
def building_predictions(building_id: UUID, db: Session = Depends(get_db)) -> list[ModelPrediction]:
    if db.get(Building, building_id) is None:
        raise HTTPException(404, "Building not found")
    return db.scalars(select(ModelPrediction).where(ModelPrediction.building_id == building_id).order_by(ModelPrediction.created_at.desc())).all()


@app.get("/api/v1/analysis-jobs/{job_id}/statistics", response_model=StatisticsResponse)
def job_statistics(job_id: UUID, db: Session = Depends(get_db)) -> dict[str, int]:
    return job_or_404(db, job_id).counts or {}


@app.get("/api/v1/analysis-jobs/{job_id}/export")
def export_job(job_id: UUID, format: str = Query(pattern="^(geojson|csv)$"), status: str | None = None, db: Session = Depends(get_db)) -> Response:
    features = filtered_job_features(db, job_id, set(status.split(",")) if status else None)
    if format == "geojson":
        import json
        return Response(json.dumps({"type": "FeatureCollection", "features": features}), media_type="application/geo+json", headers={"Content-Disposition": f"attachment; filename=roofer-{job_id}.geojson"})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["building_id", "status", "source_provider", "source_object_type", "source_object_id", "match_confidence", "registry_source_status"])
    writer.writeheader()
    for feature in features:
        props = feature["properties"]
        writer.writerow({key: props.get(key) for key in writer.fieldnames})
    return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=roofer-{job_id}.csv"})


@app.put("/api/v1/matches/{match_id}/review")
def review_match(match_id: UUID, request: ReviewRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    match = db.get(BuildingRegistryMatch, match_id)
    if match is None:
        raise HTTPException(404, "Match not found")
    match.manual_reviewed = request.reviewed
    match.review_note = request.note
    match.reviewed_at = datetime.now(timezone.utc) if request.reviewed else None
    db.commit()
    return {"id": str(match.id), "manual_reviewed": match.manual_reviewed, "reviewed_at": match.reviewed_at}


@app.get("/api/v1/registry/sync/{checkpoint_id}", response_model=SyncResponse)
def get_sync_checkpoint(checkpoint_id: UUID, db: Session = Depends(get_db)) -> SyncResponse:
    checkpoint = db.get(RegistrySyncCheckpoint, checkpoint_id)
    if checkpoint is None:
        raise HTTPException(404, "Synchronization checkpoint not found")
    return SyncResponse(checkpoint_id=checkpoint.id, status=checkpoint.status, processed_count=checkpoint.processed_count, total_expected=checkpoint.total_expected, next_start_index=checkpoint.next_start_index)


@app.post("/api/v1/registry/sync", response_model=SyncResponse)
async def sync_registry(request: SyncRequest, db: Session = Depends(get_db)) -> SyncResponse:
    if not request.full_country and request.bbox is None and request.teryt is None:
        raise HTTPException(422, "Provide bbox, TERYT, or full_country=true")
    try:
        checkpoint = await synchronize_layer(db, GeoAzbestWfsClient(settings), request.layer, request.bbox, request.teryt, request.full_country)
    except GeoAzbestUnavailable as error:
        raise HTTPException(503, {"status": "source_unavailable", "detail": str(error)}) from error
    return SyncResponse(checkpoint_id=checkpoint.id, status=checkpoint.status, processed_count=checkpoint.processed_count, total_expected=checkpoint.total_expected, next_start_index=checkpoint.next_start_index)


@app.get("/api/v1/registry/capabilities")
async def registry_capabilities(layer: str | None = None) -> dict[str, Any]:
    client = GeoAzbestWfsClient(settings)
    try:
        document = await (client.discover_schema(layer) if layer else client.get_capabilities())
    except (GeoAzbestUnavailable, ValueError) as error:
        raise HTTPException(503, {"status": "source_unavailable", "detail": str(error)}) from error
    return {"document": document, "layers": sorted(WFS_LAYERS)}


@app.get("/api/v1/imagery/available", response_model=list[ImageryLayerResponse])
async def available_imagery(bbox: str = Query(pattern=r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?$")) -> list[ImageryDescriptor]:
    try:
        min_lon, min_lat, max_lon, max_lat = map(float, bbox.split(","))
        area = box(min_lon, min_lat, max_lon, max_lat)
        if not area.is_valid or min_lon >= max_lon or min_lat >= max_lat:
            raise ValueError
    except ValueError as error:
        raise HTTPException(422, "Invalid bounding box") from error
    return await build_imagery_provider(settings).available_for_area(area)


def descriptor_by_id(layer_id: str) -> ImageryDescriptor:
    if layer_id == "gugik-ortho-current":
        return ImageryDescriptor(layer_id, "GUGiK Geoportal", "Raster", 2025, None, None, None, "Orthophotomap: GUGiK / Geoportal.gov.pl", "Subject to Geoportal terms.", {"kind": "wms", "url": GUGIK_WMS_CURRENT, "layers": "Raster", "detail_url": GUGIK_WMS_CURRENT_DETAIL}, True)
    if layer_id.startswith("gugik-ortho-") and layer_id[12:].isdigit() and 2012 <= int(layer_id[12:]) <= 2025:
        year = int(layer_id[12:])
        return ImageryDescriptor(layer_id, "GUGiK Geoportal", "Raster", year, str(year), None, None, "Orthophotomap: GUGiK / Geoportal.gov.pl", "Subject to Geoportal terms.", {"kind": "wms", "url": GUGIK_WMS_TIME, "layers": "Raster", "time": f"{year}-01-01T00:00:00.000Z", "detail_url": GUGIK_WMS_TIME_DETAIL}, True)
    raise HTTPException(404, "Unknown imagery layer")


@app.get("/api/v1/imagery/tiles/{layer_id}/{z}/{x}/{y}.jpg")
async def imagery_tile(layer_id: str, z: int, x: int, y: int) -> Response:
    if not (0 <= z <= 22 and 0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(422, "Invalid tile coordinates")
    layer = descriptor_by_id(layer_id)
    cache_key = f"{layer_id}/{z}/{x}/{y}"
    cached = tile_cache.get(cache_key)
    if cached is not None:
        tile_cache.move_to_end(cache_key)
        return Response(cached[0], media_type=cached[1], headers={"Cache-Control": "public, max-age=86400", "X-Tile-Cache": "hit"})
    content, content_type = await fetch_imagery_tile(tile_request_candidates(layer, z, x, y))
    tile_cache[cache_key] = (content, content_type)
    while len(tile_cache) > TILE_CACHE_LIMIT:
        tile_cache.popitem(last=False)
    return Response(content, media_type=content_type, headers={"Cache-Control": "public, max-age=86400", "X-Tile-Cache": "miss"})


@app.get("/api/v1/geocode", response_model=list[GeocodeResult])
async def geocode(q: str = Query(min_length=3, max_length=180)) -> list[GeocodeResult]:
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Roofer HackMIT demo contact: demo@example.invalid"}) as client:
            response = await client.get("https://nominatim.openstreetmap.org/search", params={"q": f"{q}, Poland", "format": "jsonv2", "limit": 5, "addressdetails": 1, "accept-language": "en"})
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(503, {"status": "source_unavailable", "detail": str(error)}) from error
    return [GeocodeResult(label=item["display_name"], center=(float(item["lon"]), float(item["lat"])), bbox=[float(item["boundingbox"][2]), float(item["boundingbox"][0]), float(item["boundingbox"][3]), float(item["boundingbox"][1])]) for item in data]
