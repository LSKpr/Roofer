import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import shape
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.fixtures.demo import DEMO_BUILDINGS, DEMO_REGISTRY
from app.models import AnalysisJob, AnalysisJobBuilding, Building, BuildingRegistryMatch, RegistryFeature
from app.providers.buildings import BuildingRecord, ExternalBuildingServiceUnavailable, build_provider
from app.providers.geoazbest import GeoAzbestUnavailable, GeoAzbestWfsClient, feature_values, upsert_feature
from app.services.geo import area_km2, validate_polygon
from app.services.matching import BuildingCandidate, RegistryCandidate, aggregate_status, match_building


class AnalysisValidationError(ValueError):
    pass


def validate_analysis_area(geometry_json: dict[str, Any], settings: Settings):
    area = validate_polygon(geometry_json)
    area_size = area_km2(area)
    if area_size > settings.max_analysis_area_km2:
        raise AnalysisValidationError(f"Area is {area_size:.2f} km²; maximum is {settings.max_analysis_area_km2:.2f} km²")
    return area


def update_job(session: Session, job: AnalysisJob, progress: int, stage: str, status: str = "running") -> None:
    job.progress = progress
    job.stage = stage
    job.status = status
    session.commit()


def append_job_error(job: AnalysisJob, source: str, message: str) -> None:
    errors = list(job.errors or [])
    errors.append({"source": source, "message": message})
    job.errors = errors


def demo_building_records(area) -> list[BuildingRecord]:
    records = []
    for item in DEMO_BUILDINGS:
        geometry = validate_polygon(item["geometry"])
        if geometry.intersects(area):
            records.append(BuildingRecord(item["type"], item["id"], geometry, item["tags"]))
    return records


def load_demo_registry(session: Session, area) -> list[RegistryFeature]:
    records = []
    for item in DEMO_REGISTRY:
        geometry = shape(item["geometry"])
        if not geometry.intersects(area):
            continue
        values = {
            "geoazbest_layer": item["layer"],
            "source_feature_id": item["id"],
            "location_id": item["location_id"],
            "parcel_number": item["parcel_number"],
            "teryt": item["teryt"],
            "geometry": from_shape(geometry, srid=4326),
            "registry_status": item["status"],
            "urgency": str(item["properties"].get("stopien_pilnosci_opis") or item["properties"].get("stopien_pilnosci") or "") or None,
            "planned_removal_year": item["properties"].get("planowany_rok_unieszkodliwienia_wyrobu"),
            "actual_removal_year": item["properties"].get("rok_unieszkodliwienia_wyrobu"),
            "inventory_amount": item["properties"].get("ilosc_wyrobu"),
            "disposed_amount": item["properties"].get("ilosc_przekazana_do_unieszkodliwienia"),
            "raw_properties": item["properties"],
            "synchronized_at": datetime.now(timezone.utc),
        }
        records.append(upsert_feature(session, values))
    session.commit()
    return records


def persist_buildings(session: Session, records: list[BuildingRecord], provider_name: str) -> list[Building]:
    if not records:
        return []
    source_ids = [record.object_id for record in records]
    existing = {
        (building.source_object_type, building.source_object_id): building
        for building in session.scalars(select(Building).where(Building.source_provider == provider_name, Building.source_object_id.in_(source_ids))).all()
    }
    persisted: list[Building] = []
    for record in records:
        key = (record.object_type, record.object_id)
        building = existing.get(key)
        geometry = from_shape(record.geometry, srid=4326)
        centroid = from_shape(record.geometry.centroid, srid=4326)
        if building is None:
            building = Building(source_provider=provider_name, source_object_type=record.object_type, source_object_id=record.object_id, geometry=geometry, centroid=centroid, osm_tags=record.tags, source_updated_at=record.source_updated_at)
            session.add(building)
        else:
            building.geometry = geometry
            building.centroid = centroid
            building.osm_tags = record.tags
            building.source_updated_at = record.source_updated_at
        persisted.append(building)
    session.flush()
    return persisted


def registry_records_for_area(session: Session, area) -> list[RegistryFeature]:
    return session.scalars(select(RegistryFeature).where(func.ST_Intersects(RegistryFeature.geometry, from_shape(area, srid=4326)))).all()


def compute_statistics(statuses: list[str], registry_features: list[RegistryFeature]) -> dict[str, int]:
    return {
        "total_osm_buildings": len(statuses),
        "registry_listed_asbestos_buildings": statuses.count("listed"),
        "cleaned_buildings": statuses.count("cleaned"),
        "not_listed_buildings": statuses.count("not_listed"),
        "ambiguous_matches": statuses.count("ambiguous"),
        "unknown_buildings": statuses.count("unknown"),
        "records_with_removal_years": sum(feature.actual_removal_year is not None for feature in registry_features),
        "records_with_incomplete_metadata": sum(not feature.location_id or feature.inventory_amount is None for feature in registry_features),
    }


async def run_analysis_job(session_factory, job_id: UUID, settings: Settings) -> None:
    with session_factory() as session:
        job = session.get(AnalysisJob, job_id)
        if job is None:
            return
        area = validate_polygon(to_shape(job.requested_geometry))
        job.started_at = datetime.now(timezone.utc)
        update_job(session, job, 5, "Fetching building footprints")
        provider = build_provider(settings, session_factory)
        provider_name = settings.building_provider
        try:
            building_records = await provider.fetch_buildings(area)
        except ExternalBuildingServiceUnavailable as error:
            append_job_error(job, "overpass", f"source_unavailable: {error}")
            if settings.demo_fallback_enabled:
                building_records = demo_building_records(area)
                provider_name = "demo_fixture"
            else:
                building_records = []
        update_job(session, job, 28, "Loading official registry data")
        registry_available = True
        source_status = "available"
        if settings.building_provider == "demo_fixture":
            registry_features = load_demo_registry(session, area)
            source_status = "demo_fixture"
        else:
            client = GeoAzbestWfsClient(settings)
            layers = ["wfs:budynki_z_azbestem", "wfs:budynki_oczyszczone", "wfs:wyroby_dzialki"]
            for layer in layers:
                try:
                    from app.providers.geoazbest import synchronize_layer
                    await synchronize_layer(session, client, layer, list(area.bounds), full_country=False)
                except GeoAzbestUnavailable as error:
                    append_job_error(job, "geoazbest", f"source_unavailable ({layer}): {error}")
                    if layer != "wfs:wyroby_dzialki":
                        registry_available = False
            if not registry_available and settings.demo_fallback_enabled:
                registry_features = load_demo_registry(session, area)
                registry_available = True
                source_status = "demo_fixture"
            elif registry_available:
                registry_features = registry_records_for_area(session, area)
            else:
                registry_features = []
                source_status = "source_unavailable"
        job.registry_source_status = source_status
        update_job(session, job, 55, "Matching spatial records")
        buildings = persist_buildings(session, building_records, provider_name)
        session.flush()
        building_ids = [building.id for building in buildings]
        if building_ids:
            session.execute(delete(BuildingRegistryMatch).where(BuildingRegistryMatch.building_id.in_(building_ids)))
            session.execute(delete(AnalysisJobBuilding).where(AnalysisJobBuilding.analysis_job_id == job.id, AnalysisJobBuilding.building_id.in_(building_ids)))
        registry_candidates = {
            str(feature.id): RegistryCandidate(str(feature.id), to_shape(feature.geometry), feature.location_id, feature.parcel_number, feature.registry_status)
            for feature in registry_features
        }
        requested_years = sorted(set(job.requested_years or []))
        statuses: list[str] = []
        for building in buildings:
            building_geometry = to_shape(building.geometry)
            decisions = match_building(BuildingCandidate(str(building.id), building_geometry, building.osm_tags), list(registry_candidates.values()))
            for decision in decisions:
                registry_feature = next(feature for feature in registry_features if str(feature.id) == decision.registry_source_id)
                session.add(BuildingRegistryMatch(building_id=building.id, registry_feature_id=registry_feature.id, match_method=decision.match_method, intersection_area_m2=decision.intersection_area_m2, overlap_ratio=decision.overlap_ratio, confidence=decision.confidence, ambiguity_flag=decision.ambiguity_flag))
            status = aggregate_status(decisions, registry_candidates, registry_available)
            matched_features = [feature for feature in registry_features if str(feature.id) in {decision.registry_source_id for decision in decisions}]
            removal_years = [feature.actual_removal_year for feature in matched_features if feature.actual_removal_year]
            before_after = any(any(year < removal < max(requested_years, default=removal) for year in requested_years) and any(year > removal for year in requested_years) for removal in removal_years)
            session.add(AnalysisJobBuilding(analysis_job_id=job.id, building_id=building.id, status=status, registry_source_status=source_status if registry_available else "source_unavailable", has_before_after_imagery=before_after))
            statuses.append(status)
        session.commit()
        update_job(session, job, 82, "Preparing map results")
        job.counts = compute_statistics(statuses, registry_features)
        job.progress = 100
        job.stage = "Complete"
        job.status = "complete"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()


def create_analysis_job(session: Session, geometry: dict[str, Any], requested_years: list[int], settings: Settings) -> AnalysisJob:
    validate_analysis_area(geometry, settings)
    job = AnalysisJob(requested_geometry=from_shape(validate_polygon(geometry), srid=4326), requested_years=requested_years, status="queued", stage="Queued", registry_source_status="unknown")
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
