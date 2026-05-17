from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select

from app.db.base import session_factory
from app.db.models.document import Document
from app.db.models.ingestion import ParsedArtifact as ParsedArtifactRecord
from app.repositories.ingestion import (
    ensure_ingestion_stages,
    get_stages_for_run,
    try_claim_ingestion_run,
    update_run_status,
    update_stage_status,
)
from app.schemas.parsed_artifacts import ParsedArtifact as ParsedArtifactSchema
from app.schemas.parsed_artifacts import normalize_parsed_artifact_payload
from app.services.ocr import OcrService
from app.services.parsers.base import DocumentParser
from app.services.storage import StorageAdapter
from app.workflows.stages import run_parse_stage, run_persist_artifact_stage, run_chunk_stage, run_quality_report_stage
from app.repositories.chunks import persist_chunks

logger = logging.getLogger(__name__)

STAGE_NAMES = ["parse", "persist_artifact", "chunk", "quality_report"]


class PipelineRunner:
    """Backend-neutral ingestion pipeline executor.

    Shared by both the in-process dispatcher and the Temporal activity bridge
    so that business logic is not duplicated between orchestration backends.
    """

    def __init__(
        self,
        *,
        parser: DocumentParser,
        parser_backend: str,
        parser_profile: str,
        ocr_service: OcrService | None = None,
        storage: StorageAdapter | None = None,
    ) -> None:
        self._parser = parser
        self._parser_backend = parser_backend
        self._parser_profile = parser_profile
        self._ocr_service = ocr_service
        self._storage = storage

    def run(self, run_id: UUID) -> None:
        """Execute the full ingestion pipeline for a single run.

        This method is synchronous/thread-friendly so both in-process dispatch
        and Temporal activity execution can call the same code.
        """
        claimed_run = try_claim_ingestion_run(run_id=run_id)
        if claimed_run is None:
            logger.info("Run %s could not be claimed; skipping duplicate dispatch.", run_id)
            return

        with session_factory() as session:
            if session.bind is None:
                logger.error("No database bind, cannot execute pipeline for run %s.", run_id)
                update_run_status(run_id=run_id, status="failed")
                return

            tenant_id = claimed_run.tenant_id
            document_id = claimed_run.document_id

            doc = session.scalar(select(Document).where(Document.id == document_id))
            object_key = doc.object_key if doc else ""
            content_type = "application/octet-stream"
            source_type = doc.source_type if doc else "loose_document"

        stages = ensure_ingestion_stages(run_id=run_id, tenant_id=tenant_id, stage_names=STAGE_NAMES)
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
                ocr_service=self._ocr_service,
                local_source_path=local_source_path,
            )

            # If parse was skipped (already completed), load artifact from DB
            if artifact is None:
                with session_factory() as session:
                    record = session.scalar(
                        select(ParsedArtifactRecord).where(ParsedArtifactRecord.run_id == run_id)
                    )
                    if record is not None:
                        artifact = ParsedArtifactSchema.model_validate(
                            normalize_parsed_artifact_payload(record.artifact_json)
                        )
                    else:
                        update_stage_status(
                            stage_id=stage_map["parse"].id,
                            status="queued",
                            details={"retry_reset_reason": "artifact_missing_for_completed_parse"},
                        )
                        artifact = run_parse_stage(
                            run_id=run_id,
                            stage_id=stage_map["parse"].id,
                            document_id=document_id,
                            object_key=object_key or "",
                            content_type=content_type,
                            profile=self._parser_profile,
                            parser_backend=self._parser_backend,
                            parser=self._parser,
                            ocr_service=self._ocr_service,
                            local_source_path=local_source_path,
                        )

            # Stage 2: Persist artifact
            if artifact is not None:
                run_persist_artifact_stage(
                    run_id=run_id,
                    stage_id=stage_map["persist_artifact"].id,
                    artifact=artifact,
                )

            # Stage 3: Chunk
            if artifact is not None:
                chunks = run_chunk_stage(
                    run_id=run_id,
                    stage_id=stage_map["chunk"].id,
                    document_id=document_id,
                    artifact=artifact,
                    source_type=source_type,
                )
                if chunks is not None:
                    persist_chunks(
                        run_id=run_id,
                        document_id=document_id,
                        chunks=chunks,
                    )

            # Stage 4: Quality report
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
