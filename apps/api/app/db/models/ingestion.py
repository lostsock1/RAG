from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, json_type


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(length=32), nullable=False, default="queued", server_default="queued")
    workflow_backend: Mapped[str] = mapped_column(String(length=32), nullable=False, default="temporal", server_default="temporal")
    parser_backend: Mapped[str] = mapped_column(String(length=64), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(length=128), nullable=False)
    worker_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class IngestionStage(Base):
    __tablename__ = "ingestion_stages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    stage_name: Mapped[str] = mapped_column(String(length=64), nullable=False)
    status: Mapped[str] = mapped_column(String(length=32), nullable=False, default="queued", server_default="queued")
    details: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict, server_default="{}")
    worker_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ParsedArtifact(Base):
    __tablename__ = "parsed_artifacts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(length=64), nullable=False, default="structured", server_default="structured")
    artifact_json: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict, server_default="{}")
    artifact_hash: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class QualityReport(Base):
    __tablename__ = "quality_reports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    quality_score: Mapped[str] = mapped_column(String(length=32), nullable=False)
    summary: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict, server_default="{}")
    warnings: Mapped[list] = mapped_column(json_type(), nullable=False, default=list, server_default="[]")
    raw_report_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
