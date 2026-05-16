from __future__ import annotations

import asyncio
import logging
from typing import Protocol
from uuid import UUID

from sqlalchemy import select

from app.db.base import session_factory
from app.db.models.document import Document
from app.db.models.ingestion import IngestionRun, ParsedArtifact as ParsedArtifactRecord
from app.repositories.ingestion import (
    create_ingestion_stages,
    get_stages_for_run,
    update_run_status,
    update_stage_status,
)
from app.schemas.parsed_artifacts import ParsedArtifact as ParsedArtifactSchema
from app.services.parsers.base import DocumentParser
from app.services.storage import StorageAdapter
from app.workflows.stages import run_parse_stage, run_persist_artifact_stage, run_quality_report_stage

logger = logging.getLogger(__name__)

STAGE_NAMES = ["parse", "persist_artifact", "quality_report"]


class WorkflowDispatcher(Protocol):
    async def dispatch(self, run_id: UUID) -> None: ...


class InProcessDispatcher:
    """In-process dispatcher that runs the ingestion pipeline via asyncio.create_task."""

    def __init__(
        self,
        parser: DocumentParser,
        parser_backend: str,
        parser_profile: str,
        storage: StorageAdapter | None = None,
    ) -> None:
        self._parser = parser
        self._parser_backend = parser_backend
        self._parser_profile = parser_profile
        self._storage = storage

    async def dispatch(self, run_id: UUID) -> None:
        loop = asyncio.get_event_loop()
        loop.create_task(self._run_pipeline(run_id))

    async def _run_pipeline(self, run_id: UUID) -> None:
        try:
            await asyncio.to_thread(self._execute_pipeline, run_id)
        except Exception:
            logger.exception("Ingestion pipeline failed unexpectedly for run %s", run_id)

    def _execute_pipeline(self, run_id: UUID) -> None:
        # Load run and document metadata
        with session_factory() as session:
            if session.bind is None:
                logger.error("No database bind, cannot execute pipeline for run %s.", run_id)
                return

            run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
            if run is None:
                logger.error("Ingestion run %s not found, cannot dispatch.", run_id)
                return

            tenant_id = run.tenant_id
            document_id = run.document_id

            doc = session.scalar(select(Document).where(Document.id == document_id))
            object_key = doc.object_key if doc else ""
            content_type = "application/octet-stream"

        # Mark run as running
        update_run_status(run_id=run_id, status="running")

        # Create stage records
        stages = create_ingestion_stages(run_id=run_id, tenant_id=tenant_id, stage_names=STAGE_NAMES)
        stage_map = {s.stage_name: s for s in stages}

        # Materialize object for parsing if storage adapter is available
        materialized = None
        local_source_path = None
        if self._storage is not None:
            materialized = self._storage.materialize_for_read(object_key=object_key or "")
            local_source_path = str(materialized.local_path)

        try:
            # Stage 1: Parse
            artifact = run_parse_stage(
                run_id=run_id,
                stage_id=stage_map["parse"].id,
                document_id=document_id,
                object_key=object_key or "",
                content_type=content_type,
                profile=self._parser_profile,
                parser_backend=self._parser_backend,
                parser=self._parser,
                local_source_path=local_source_path,
            )

            # If parse was skipped (already completed), load artifact from DB
            if artifact is None:
                with session_factory() as session:
                    record = session.scalar(
                        select(ParsedArtifactRecord).where(ParsedArtifactRecord.run_id == run_id)
                    )
                    if record is not None:
                        artifact = ParsedArtifactSchema.model_validate(record.artifact_json)

            # Stage 2: Persist artifact
            if artifact is not None:
                run_persist_artifact_stage(
                    run_id=run_id,
                    stage_id=stage_map["persist_artifact"].id,
                    artifact=artifact,
                )

            # Stage 3: Quality report
            if artifact is not None:
                run_quality_report_stage(
                    run_id=run_id,
                    stage_id=stage_map["quality_report"].id,
                    artifact=artifact,
                )

            update_run_status(run_id=run_id, status="completed")

        except Exception as exc:
            logger.exception("Stage failed for run %s: %s", run_id, exc)
            # Mark any running stages as failed
            failed_stages = get_stages_for_run(run_id=run_id)
            for stage in failed_stages:
                if stage.status == "running":
                    update_stage_status(stage_id=stage.id, status="failed", details={"error": str(exc)})
            update_run_status(run_id=run_id, status="failed")
        finally:
            if materialized is not None and materialized.cleanup is not None:
                materialized.cleanup()
