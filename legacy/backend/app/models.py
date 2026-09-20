import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Building(Timestamped, Base):
    __tablename__ = "buildings"
    __table_args__ = (UniqueConstraint("source_provider", "source_object_type", "source_object_id", name="uq_building_source"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    source_object_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_object_id: Mapped[str] = mapped_column(String(80), nullable=False)
    geometry: Mapped[Any] = mapped_column(Geometry("GEOMETRY", srid=4326, spatial_index=True), nullable=False)
    centroid: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    osm_tags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    matches: Mapped[list["BuildingRegistryMatch"]] = relationship(back_populates="building", cascade="all, delete-orphan")
    predictions: Mapped[list["ModelPrediction"]] = relationship(back_populates="building", cascade="all, delete-orphan")


class RegistryFeature(Timestamped, Base):
    __tablename__ = "registry_features"
    __table_args__ = (UniqueConstraint("geoazbest_layer", "source_feature_id", name="uq_registry_source"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    geoazbest_layer: Mapped[str] = mapped_column(String(80), nullable=False)
    source_feature_id: Mapped[str] = mapped_column(String(160), nullable=False)
    location_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    parcel_number: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    teryt: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    geometry: Mapped[Any] = mapped_column(Geometry("GEOMETRY", srid=4326, spatial_index=True), nullable=False)
    registry_status: Mapped[str] = mapped_column(String(30), nullable=False)
    urgency: Mapped[str | None] = mapped_column(String(80), nullable=True)
    planned_removal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_removal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inventory_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    disposed_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_properties: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    synchronized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    matches: Mapped[list["BuildingRegistryMatch"]] = relationship(back_populates="registry_feature", cascade="all, delete-orphan")


class BuildingRegistryMatch(Timestamped, Base):
    __tablename__ = "building_registry_matches"
    __table_args__ = (UniqueConstraint("building_id", "registry_feature_id", name="uq_building_registry_match"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    building_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False, index=True)
    registry_feature_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("registry_features.id", ondelete="CASCADE"), nullable=False, index=True)
    match_method: Mapped[str] = mapped_column(String(40), nullable=False)
    intersection_area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    overlap_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    ambiguity_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manual_reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    building: Mapped[Building] = relationship(back_populates="matches")
    registry_feature: Mapped[RegistryFeature] = relationship(back_populates="matches")


class ImageryLayer(Timestamped, Base):
    __tablename__ = "imagery_layers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    layer_identifier: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    acquisition_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    acquisition_date_range: Mapped[str | None] = mapped_column(String(160), nullable=True)
    resolution_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage: Mapped[Any | None] = mapped_column(Geometry("GEOMETRY", srid=4326, spatial_index=True), nullable=True)
    service_configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    attribution: Mapped[str] = mapped_column(Text, nullable=False)
    license_metadata: Mapped[str] = mapped_column(Text, nullable=False)


class AnalysisJob(Timestamped, Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requested_geometry: Mapped[Any] = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=False)
    requested_years: Mapped[list[int]] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stage: Mapped[str] = mapped_column(String(120), default="Queued", nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    errors: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list, nullable=False)
    registry_source_status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnalysisJobBuilding(Base):
    __tablename__ = "analysis_job_buildings"
    __table_args__ = (UniqueConstraint("analysis_job_id", "building_id", name="uq_analysis_job_building"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    building_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    registry_source_status: Mapped[str] = mapped_column(String(40), nullable=False)
    has_before_after_imagery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RegistrySyncCheckpoint(Timestamped, Base):
    __tablename__ = "registry_sync_checkpoints"
    __table_args__ = (UniqueConstraint("layer", "scope_key", name="uq_sync_scope"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    layer: Mapped[str] = mapped_column(String(80), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(160), nullable=False)
    next_start_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    total_expected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelPrediction(Base):
    __tablename__ = "model_predictions"
    __table_args__ = (Index("ix_prediction_building_imagery", "building_id", "imagery_layer_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    building_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False)
    imagery_layer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("imagery_layers.id", ondelete="CASCADE"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_version: Mapped[str] = mapped_column(String(120), nullable=False)
    probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_class: Mapped[str | None] = mapped_column(String(80), nullable=True)
    explanation_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    building: Mapped[Building] = relationship(back_populates="predictions")
