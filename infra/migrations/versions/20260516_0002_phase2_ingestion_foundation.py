"""phase 2 ingestion foundation schema

Revision ID: 20260516_0002
Revises: 20260515_0001
Create Date: 2026-05-16 00:02:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260516_0002"
down_revision = "20260515_0001"
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.String()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("workflow_backend", sa.String(length=32), nullable=False, server_default="temporal"),
        sa.Column("parser_backend", sa.String(length=64), nullable=False),
        sa.Column("source_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_ingestion_runs_document_id_documents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_ingestion_runs_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
    )
    op.create_index(op.f("ix_ingestion_runs_document_id"), "ingestion_runs", ["document_id"], unique=False)
    op.create_index(op.f("ix_ingestion_runs_tenant_id"), "ingestion_runs", ["tenant_id"], unique=False)

    op.create_table(
        "ingestion_stages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("stage_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("details", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["ingestion_runs.id"], name=op.f("fk_ingestion_stages_run_id_ingestion_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_ingestion_stages_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_stages")),
    )
    op.create_index(op.f("ix_ingestion_stages_run_id"), "ingestion_stages", ["run_id"], unique=False)
    op.create_index(op.f("ix_ingestion_stages_tenant_id"), "ingestion_stages", ["tenant_id"], unique=False)

    op.create_table(
        "parsed_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False, server_default="structured"),
        sa.Column("artifact_json", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("artifact_hash", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["ingestion_runs.id"], name=op.f("fk_parsed_artifacts_run_id_ingestion_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_parsed_artifacts_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parsed_artifacts")),
    )
    op.create_index(op.f("ix_parsed_artifacts_run_id"), "parsed_artifacts", ["run_id"], unique=False)
    op.create_index(op.f("ix_parsed_artifacts_tenant_id"), "parsed_artifacts", ["tenant_id"], unique=False)

    op.create_table(
        "quality_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("quality_score", sa.String(length=32), nullable=False),
        sa.Column("summary", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("warnings", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("raw_report_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["ingestion_runs.id"], name=op.f("fk_quality_reports_run_id_ingestion_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_quality_reports_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quality_reports")),
    )
    op.create_index(op.f("ix_quality_reports_run_id"), "quality_reports", ["run_id"], unique=False)
    op.create_index(op.f("ix_quality_reports_tenant_id"), "quality_reports", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_quality_reports_tenant_id"), table_name="quality_reports")
    op.drop_index(op.f("ix_quality_reports_run_id"), table_name="quality_reports")
    op.drop_table("quality_reports")
    op.drop_index(op.f("ix_parsed_artifacts_tenant_id"), table_name="parsed_artifacts")
    op.drop_index(op.f("ix_parsed_artifacts_run_id"), table_name="parsed_artifacts")
    op.drop_table("parsed_artifacts")
    op.drop_index(op.f("ix_ingestion_stages_tenant_id"), table_name="ingestion_stages")
    op.drop_index(op.f("ix_ingestion_stages_run_id"), table_name="ingestion_stages")
    op.drop_table("ingestion_stages")
    op.drop_index(op.f("ix_ingestion_runs_tenant_id"), table_name="ingestion_runs")
    op.drop_index(op.f("ix_ingestion_runs_document_id"), table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
