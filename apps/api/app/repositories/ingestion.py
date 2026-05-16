from __future__ import annotations

from hashlib import sha256
import json
from uuid import UUID

from sqlalchemy import delete, select

from app.db.base import session_factory
from app.db.models.acl import AclGrant
from app.db.models.audit import AuditEvent
from app.db.models.document import Document
from app.db.models.ingestion import IngestionRun, IngestionStage, ParsedArtifact as ParsedArtifactRecord, QualityReport
from app.repositories.documents import resolve_group_ids_for_context
from app.schemas.parsed_artifacts import ParsedArtifact
from app.services.quality_report import build_quality_report
from app.services.acl_service import build_document_acl_filter


def create_ingestion_run(*, document_id: UUID, tenant_id: UUID, parser_backend: str, source_hash: str) -> IngestionRun:
    run = IngestionRun(
        document_id=document_id,
        tenant_id=tenant_id,
        parser_backend=parser_backend,
        source_hash=source_hash,
        status="queued",
        workflow_backend="scaffold",
    )

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        session.add(run)
        session.commit()
        session.refresh(run)
        return run


def list_ingestion_runs_for_context(*, tenant_id: str, user_id: str, group_ids: list[str]) -> list[IngestionRun]:
    tenant_uuid = UUID(tenant_id)
    user_uuid = UUID(user_id)

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        group_uuids = resolve_group_ids_for_context(
            session=session,
            tenant_id=tenant_uuid,
            group_ids=group_ids,
        )

        runs = session.scalars(
            select(IngestionRun)
            .join(Document, Document.id == IngestionRun.document_id)
            .join(AclGrant, AclGrant.document_id == Document.id)
            .where(
                build_document_acl_filter(
                    tenant_id=tenant_uuid,
                    user_id=user_uuid,
                    group_ids=group_uuids,
                )
            )
            .order_by(IngestionRun.created_at.desc())
        ).all()

        return list(runs)


def get_ingestion_run_for_context(
    *,
    job_id: UUID,
    tenant_id: str,
    user_id: str,
    group_ids: list[str],
) -> IngestionRun | None:
    tenant_uuid = UUID(tenant_id)
    user_uuid = UUID(user_id)

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        group_uuids = resolve_group_ids_for_context(
            session=session,
            tenant_id=tenant_uuid,
            group_ids=group_ids,
        )

        return session.scalar(
            select(IngestionRun)
            .join(Document, Document.id == IngestionRun.document_id)
            .join(AclGrant, AclGrant.document_id == Document.id)
            .where(
                IngestionRun.id == job_id,
                build_document_acl_filter(
                    tenant_id=tenant_uuid,
                    user_id=user_uuid,
                    group_ids=group_uuids,
                ),
            )
        )


def write_ingestion_job_get_denied_audit_event(*, tenant_id: str, user_id: str, job_id: UUID) -> None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Audit persistence is not configured: session_factory has no database bind."
            )

        session.add(
            AuditEvent(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id),
                action="ingestion.job.get.denied",
                resource_type="ingestion_run",
                resource_id=None,
                details={
                    "job_id": str(job_id),
                    "reason": "not_found_or_denied",
                },
            )
        )
        session.commit()


def store_parsed_artifact(*, run_id: UUID, artifact: ParsedArtifact) -> ParsedArtifactRecord:
    artifact_payload = artifact.model_dump(mode="json")
    artifact_hash = sha256(json.dumps(artifact_payload, sort_keys=True).encode("utf-8")).hexdigest()
    report = build_quality_report(artifact)

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        if run is None:
            raise RuntimeError("Parsed artifact persistence failed: the ingestion run does not exist.")

        existing_artifact = session.scalar(
            select(ParsedArtifactRecord).where(ParsedArtifactRecord.run_id == run.id).order_by(ParsedArtifactRecord.created_at.asc())
        )
        if existing_artifact is None:
            artifact_record = ParsedArtifactRecord(
                run_id=run.id,
                tenant_id=run.tenant_id,
                artifact_type="structured",
                artifact_json=artifact_payload,
                artifact_hash=artifact_hash,
            )
            session.add(artifact_record)
            session.flush()
        else:
            artifact_record = existing_artifact
            artifact_record.artifact_type = "structured"
            artifact_record.artifact_json = artifact_payload
            artifact_record.artifact_hash = artifact_hash
            session.execute(
                delete(ParsedArtifactRecord).where(
                    ParsedArtifactRecord.run_id == run.id,
                    ParsedArtifactRecord.id != artifact_record.id,
                )
            )

        existing_report = session.scalar(
            select(QualityReport).where(QualityReport.run_id == run.id).order_by(QualityReport.created_at.asc())
        )
        if existing_report is None:
            session.add(
                QualityReport(
                    run_id=run.id,
                    tenant_id=run.tenant_id,
                    quality_score=f"{report.quality_score:.2f}",
                    summary=report.summary,
                    warnings=report.warnings,
                    raw_report_text=None,
                )
            )
        else:
            existing_report.quality_score = f"{report.quality_score:.2f}"
            existing_report.summary = report.summary
            existing_report.warnings = report.warnings
            existing_report.raw_report_text = None
            session.execute(
                delete(QualityReport).where(
                    QualityReport.run_id == run.id,
                    QualityReport.id != existing_report.id,
                )
            )

        session.commit()
        session.refresh(artifact_record)
        return artifact_record


def write_ingestion_job_get_audit_event(*, tenant_id: str, user_id: str, run: IngestionRun) -> None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Audit persistence is not configured: session_factory has no database bind."
            )

        session.add(
            AuditEvent(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id),
                action="ingestion.job.get",
                resource_type="ingestion_run",
                resource_id=run.id,
                details={
                    "job_id": str(run.id),
                    "document_id": str(run.document_id),
                    "status": run.status,
                },
            )
        )
        session.commit()


def write_ingestion_run_list_audit_event(*, tenant_id: str, user_id: str, run_ids: list[UUID]) -> None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Audit persistence is not configured: session_factory has no database bind."
            )

        session.add(
            AuditEvent(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id),
                action="ingestion.run.list",
                resource_type="ingestion_run",
                resource_id=None,
                details={
                    "filters_applied": ["acl"],
                    "run_ids": [str(run_id) for run_id in run_ids],
                    "run_count": len(run_ids),
                },
            )
        )
        session.commit()


def create_ingestion_stages(*, run_id: UUID, tenant_id: UUID, stage_names: list[str]) -> list[IngestionStage]:
    """Create IngestionStage records with status ``"queued"`` for each stage name."""
    stages = [
        IngestionStage(
            run_id=run_id,
            tenant_id=tenant_id,
            stage_name=name,
            status="queued",
        )
        for name in stage_names
    ]

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        session.add_all(stages)
        session.commit()
        for s in stages:
            session.refresh(s)
        return stages


def get_stages_for_run(*, run_id: UUID) -> list[IngestionStage]:
    """Return all stages for a run, ordered by ``created_at`` ascending."""
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        rows = session.scalars(
            select(IngestionStage)
            .where(IngestionStage.run_id == run_id)
            .order_by(IngestionStage.created_at.asc())
        ).all()
        return list(rows)


def update_stage_status(*, stage_id: UUID, status: str, details: dict | None = None) -> None:
    """Update a stage's status and optionally merge details."""
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        stage = session.scalar(select(IngestionStage).where(IngestionStage.id == stage_id))
        if stage is None:
            raise RuntimeError(f"IngestionStage {stage_id} not found.")

        stage.status = status
        if details is not None:
            merged = {**(stage.details or {}), **details}
            stage.details = merged
        session.commit()


def update_run_status(*, run_id: UUID, status: str) -> None:
    """Update an IngestionRun's status."""
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        if run is None:
            raise RuntimeError(f"IngestionRun {run_id} not found.")

        run.status = status
        session.commit()


def recover_orphaned_runs() -> int:
    """Reset all IngestionRun records with status ``"running"`` back to ``"queued"``.

    Returns the count of reset rows.
    """
    from sqlalchemy import update as sa_update

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        result = session.execute(
            sa_update(IngestionRun)
            .where(IngestionRun.status == "running")
            .values(status="queued")
        )
        session.commit()
        return result.rowcount
