from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import cast
from uuid import UUID

from sqlalchemy.engine import CursorResult
from sqlalchemy import delete, select, update as sa_update
from sqlalchemy.exc import IntegrityError

from app.db.base import session_factory
from app.db.acl_models import AclGrant
from app.db.models.audit import AuditEvent
from app.db.models.document import Document
from app.db.models.ingestion import IngestionRun, IngestionStage, ParsedArtifact as ParsedArtifactRecord, QualityReport
from app.repositories.documents import resolve_group_ids_for_context
from app.schemas.parsed_artifacts import ParsedArtifact
from app.services.quality_report import build_quality_report
from app.services.acl_service import build_document_acl_filter


def create_ingestion_run(
    *,
    document_id: UUID,
    tenant_id: UUID,
    parser_backend: str,
    source_hash: str,
    workflow_backend: str = "in_process",
    profile: str = "loose",
) -> IngestionRun:
    run = IngestionRun(
        document_id=document_id,
        tenant_id=tenant_id,
        parser_backend=parser_backend,
        source_hash=source_hash,
        status="queued",
        workflow_backend=workflow_backend,
        profile=profile,
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


def write_ingestion_job_retry_denied_audit_event(*, tenant_id: str, user_id: str, job_id: UUID) -> None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Audit persistence is not configured: session_factory has no database bind."
            )

        session.add(
            AuditEvent(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id),
                action="ingestion.job.retry.denied",
                resource_type="ingestion_run",
                resource_id=None,
                details={
                    "job_id": str(job_id),
                    "reason": "not_found_or_denied",
                },
            )
        )
        session.commit()


def write_ingestion_job_retry_conflict_audit_event(
    *, tenant_id: str, user_id: str, run: IngestionRun, current_status: str
) -> None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Audit persistence is not configured: session_factory has no database bind."
            )

        session.add(
            AuditEvent(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id),
                action="ingestion.job.retry.conflict",
                resource_type="ingestion_run",
                resource_id=run.id,
                details={
                    "job_id": str(run.id),
                    "document_id": str(run.document_id),
                    "current_status": current_status,
                    "reason": "non_retryable_status",
                },
            )
        )
        session.commit()


def write_ingestion_job_retry_audit_event(
    *, tenant_id: str, user_id: str, run: IngestionRun, previous_status: str
) -> None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Audit persistence is not configured: session_factory has no database bind."
            )

        session.add(
            AuditEvent(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id),
                action="ingestion.job.retry",
                resource_type="ingestion_run",
                resource_id=run.id,
                details={
                    "job_id": str(run.id),
                    "document_id": str(run.document_id),
                    "previous_status": previous_status,
                    "resulting_status": run.status,
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
                    raw_report_text=report.raw_payload,
                )
            )
        else:
            existing_report.quality_score = f"{report.quality_score:.2f}"
            existing_report.summary = report.summary
            existing_report.warnings = report.warnings
            existing_report.raw_report_text = report.raw_payload
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
    return ensure_ingestion_stages(run_id=run_id, tenant_id=tenant_id, stage_names=stage_names)


def ensure_ingestion_stages(*, run_id: UUID, tenant_id: UUID, stage_names: list[str]) -> list[IngestionStage]:
    """Return one canonical IngestionStage row per stage name, in input order."""

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        existing_stages = {
            stage.stage_name: stage
            for stage in session.scalars(
                select(IngestionStage).where(
                    IngestionStage.run_id == run_id,
                    IngestionStage.stage_name.in_(stage_names),
                )
            ).all()
        }

        missing_stage_names = [name for name in stage_names if name not in existing_stages]
        if missing_stage_names:
            session.add_all(
                [
                    IngestionStage(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        stage_name=name,
                        status="queued",
                    )
                    for name in missing_stage_names
                ]
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
            existing_stages = {
                stage.stage_name: stage
                for stage in session.scalars(
                    select(IngestionStage)
                    .where(
                        IngestionStage.run_id == run_id,
                        IngestionStage.stage_name.in_(stage_names),
                    )
                    .order_by(IngestionStage.created_at.asc())
                ).all()
            }

        return [existing_stages[name] for name in stage_names]


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


def try_claim_ingestion_run(*, run_id: UUID, worker_id: UUID | None = None) -> IngestionRun | None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        values: dict = {"status": "running"}
        if worker_id is not None:
            values["worker_id"] = worker_id

        result = cast(CursorResult, session.execute(
            sa_update(IngestionRun)
            .where(
                IngestionRun.id == run_id,
                IngestionRun.status == "queued",
            )
            .values(**values)
        ))
        if result.rowcount == 0:
            session.rollback()
            return None

        session.commit()
        return session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))


def prepare_ingestion_run_for_retry(*, run_id: UUID) -> IngestionRun:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        if run is None:
            raise RuntimeError(f"IngestionRun {run_id} not found.")
        if run.status not in {"failed", "queued"}:
            raise ValueError(f"Ingestion job cannot be retried from status {run.status}")

        run.status = "queued"
        stages = session.scalars(
            select(IngestionStage)
            .where(IngestionStage.run_id == run_id)
            .order_by(IngestionStage.created_at.asc())
        ).all()
        for stage in stages:
            if stage.status in {"failed", "running"}:
                stage.status = "queued"
                stage.details = {**(stage.details or {}), "retry_reset_reason": "manual_retry"}

        session.commit()
        session.refresh(run)
        return run


def recover_orphaned_runs(
    *,
    current_worker_id: UUID | None = None,
    stale_threshold_seconds: int = 300,
) -> int:
    """Reset stale IngestionRun records with status ``"running"`` back to ``"queued"``.

    A run is considered orphaned only when BOTH conditions hold:
      1. Its ``worker_id`` differs from ``current_worker_id`` (or is NULL when
         ``current_worker_id`` is provided, meaning it was created before the
         worker-id column existed).
      2. Its ``updated_at`` is older than ``stale_threshold_seconds`` ago.

    When ``current_worker_id`` is ``None`` (legacy / opt-in mode), all running
    rows are reset regardless of worker ownership — preserving the original
    single-instance behaviour.

    Returns the count of reset IngestionRun rows.
    """
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Ingestion persistence is not configured: session_factory has no database bind."
            )

        stale_cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=stale_threshold_seconds)

        run_query = select(IngestionRun).where(IngestionRun.status == "running")
        stage_query = select(IngestionStage).where(IngestionStage.status == "running")

        if current_worker_id is not None:
            # Only reset runs that belong to a *different* worker (or have no
            # worker_id) AND have not been updated recently.
            run_query = run_query.where(
                (IngestionRun.worker_id != current_worker_id) | (IngestionRun.worker_id.is_(None)),
                IngestionRun.updated_at < stale_cutoff,
            )
            stage_query = stage_query.where(
                (IngestionStage.worker_id != current_worker_id) | (IngestionStage.worker_id.is_(None)),
                IngestionStage.updated_at < stale_cutoff,
            )

        runs = session.scalars(run_query).all()
        running_stages = session.scalars(stage_query).all()

        for run in runs:
            run.status = "queued"

        for stage in running_stages:
            stage.status = "queued"
            stage.details = {**(stage.details or {}), "recovery_reset_reason": "startup_recovery"}

        session.commit()
        return len(runs)
