"""initial spatial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-09-19

"""

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def uuid_column(name: str, primary_key: bool = False, nullable: bool = False):
    return sa.Column(name, postgresql.UUID(as_uuid=True), primary_key=primary_key, nullable=nullable, server_default=sa.text("gen_random_uuid()") if primary_key else None)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table("buildings", uuid_column("id", primary_key=True), sa.Column("source_provider", sa.String(40), nullable=False), sa.Column("source_object_type", sa.String(20), nullable=False), sa.Column("source_object_id", sa.String(80), nullable=False), sa.Column("geometry", Geometry("GEOMETRY", srid=4326), nullable=False), sa.Column("centroid", Geometry("POINT", srid=4326)), sa.Column("osm_tags", postgresql.JSONB(), nullable=False), sa.Column("source_updated_at", sa.DateTime(timezone=True)), sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.UniqueConstraint("source_provider", "source_object_type", "source_object_id", name="uq_building_source"))
    op.create_table("registry_features", uuid_column("id", primary_key=True), sa.Column("geoazbest_layer", sa.String(80), nullable=False), sa.Column("source_feature_id", sa.String(160), nullable=False), sa.Column("location_id", sa.String(80)), sa.Column("parcel_number", sa.String(120)), sa.Column("teryt", sa.String(20)), sa.Column("geometry", Geometry("GEOMETRY", srid=4326), nullable=False), sa.Column("registry_status", sa.String(30), nullable=False), sa.Column("urgency", sa.String(80)), sa.Column("planned_removal_year", sa.Integer()), sa.Column("actual_removal_year", sa.Integer()), sa.Column("inventory_amount", sa.Float()), sa.Column("disposed_amount", sa.Float()), sa.Column("raw_properties", postgresql.JSONB(), nullable=False), sa.Column("synchronized_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.UniqueConstraint("geoazbest_layer", "source_feature_id", name="uq_registry_source"))
    op.create_table("imagery_layers", uuid_column("id", primary_key=True), sa.Column("provider", sa.String(80), nullable=False), sa.Column("layer_identifier", sa.String(160), nullable=False, unique=True), sa.Column("acquisition_year", sa.Integer(), nullable=False), sa.Column("acquisition_date_range", sa.String(160)), sa.Column("resolution_m", sa.Float()), sa.Column("coverage", Geometry("GEOMETRY", srid=4326)), sa.Column("service_configuration", postgresql.JSONB(), nullable=False), sa.Column("attribution", sa.Text(), nullable=False), sa.Column("license_metadata", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_table("analysis_jobs", uuid_column("id", primary_key=True), sa.Column("requested_geometry", Geometry("GEOMETRY", srid=4326), nullable=False), sa.Column("requested_years", postgresql.JSONB(), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("progress", sa.Integer(), nullable=False), sa.Column("stage", sa.String(120), nullable=False), sa.Column("counts", postgresql.JSONB(), nullable=False), sa.Column("errors", postgresql.JSONB(), nullable=False), sa.Column("registry_source_status", sa.String(40), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_table("registry_sync_checkpoints", uuid_column("id", primary_key=True), sa.Column("layer", sa.String(80), nullable=False), sa.Column("scope_key", sa.String(160), nullable=False), sa.Column("next_start_index", sa.Integer(), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("total_expected", sa.Integer()), sa.Column("processed_count", sa.Integer(), nullable=False), sa.Column("last_error", sa.Text()), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.UniqueConstraint("layer", "scope_key", name="uq_sync_scope"))
    op.create_table("building_registry_matches", uuid_column("id", primary_key=True), sa.Column("building_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False), sa.Column("registry_feature_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("registry_features.id", ondelete="CASCADE"), nullable=False), sa.Column("match_method", sa.String(40), nullable=False), sa.Column("intersection_area_m2", sa.Float(), nullable=False), sa.Column("overlap_ratio", sa.Float(), nullable=False), sa.Column("confidence", sa.Float(), nullable=False), sa.Column("ambiguity_flag", sa.Boolean(), nullable=False), sa.Column("manual_reviewed", sa.Boolean(), nullable=False), sa.Column("reviewed_at", sa.DateTime(timezone=True)), sa.Column("review_note", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.UniqueConstraint("building_id", "registry_feature_id", name="uq_building_registry_match"))
    op.create_table("analysis_job_buildings", uuid_column("id", primary_key=True), sa.Column("analysis_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False), sa.Column("building_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("registry_source_status", sa.String(40), nullable=False), sa.Column("has_before_after_imagery", sa.Boolean(), nullable=False), sa.UniqueConstraint("analysis_job_id", "building_id", name="uq_analysis_job_building"))
    op.create_table("model_predictions", uuid_column("id", primary_key=True), sa.Column("building_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False), sa.Column("imagery_layer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("imagery_layers.id", ondelete="CASCADE"), nullable=False), sa.Column("model_name", sa.String(120), nullable=False), sa.Column("model_version", sa.String(120), nullable=False), sa.Column("probability", sa.Float()), sa.Column("uncertainty", sa.Float()), sa.Column("predicted_class", sa.String(80)), sa.Column("explanation_metadata", postgresql.JSONB(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    for table, column in [("buildings", "geometry"), ("registry_features", "geometry"), ("imagery_layers", "coverage"), ("analysis_jobs", "requested_geometry"), ("local_osm_buildings", "geometry")]:
        if table != "local_osm_buildings":
            op.create_index(f"ix_{table}_{column}_gist", table, [column], postgresql_using="gist")
    for table, column in [("registry_features", "location_id"), ("registry_features", "parcel_number"), ("registry_features", "teryt"), ("analysis_jobs", "status"), ("building_registry_matches", "building_id"), ("building_registry_matches", "registry_feature_id"), ("analysis_job_buildings", "analysis_job_id"), ("analysis_job_buildings", "building_id"), ("imagery_layers", "acquisition_year")]:
        op.create_index(f"ix_{table}_{column}", table, [column])
    op.create_index("ix_prediction_building_imagery", "model_predictions", ["building_id", "imagery_layer_id"])


def downgrade() -> None:
    for table in ["model_predictions", "analysis_job_buildings", "building_registry_matches", "registry_sync_checkpoints", "analysis_jobs", "imagery_layers", "registry_features", "buildings"]:
        op.drop_table(table)
