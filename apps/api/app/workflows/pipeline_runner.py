from __future__ import annotations

import logging
from typing import TYPE_CHECKING
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
from app.workflows.stages import (
    run_parse_stage,
    run_persist_artifact_stage,
    run_chunk_stage,
    run_contextualize_stage,
    run_embed_stage,
    run_index_qdrant_stage,
    run_index_opensearch_stage,
    run_quality_report_stage,
)
from app.repositories.chunks import persist_chunks, get_chunks_as_schemas
from app.repositories.documents import get_document_index_acl_metadata
from app.services.embedders.base import Embedder
from app.services.embedders.stub import StubEmbedder
from app.services.indexers.base import VectorIndexer, LexicalIndexer
from app.services.indexers.stub import StubVectorIndexer, StubLexicalIndexer

if TYPE_CHECKING:
    from app.services.contextualizers.base import ChunkContextualizer

logger = logging.getLogger(__name__)

STAGE_NAMES = [
    "parse",
    "persist_artifact",
    "chunk",
    "embed",
    "index_qdrant",
    "index_opensearch",
    "quality_report",
]


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
        embedder: Embedder | None = None,
        vector_indexer: VectorIndexer | None = None,
        lexical_indexer: LexicalIndexer | None = None,
        contextualizer: "ChunkContextualizer | None" = None,
        worker_id: UUID | None = None,
    ) -> None:
        self._parser = parser
        self._parser_backend = parser_backend
        self._parser_profile = parser_profile
        self._ocr_service = ocr_service
        self._storage = storage
        self._embedder = embedder or StubEmbedder()
        self._vector_indexer = vector_indexer or StubVectorIndexer()
        self._lexical_indexer = lexical_indexer or StubLexicalIndexer()
        # ADR-0020: contextual augmentation is enabled iff a contextualizer is
        # injected; when None the pipeline omits the stage entirely and is
        # byte-identical to the unaugmented path.
        self._contextualizer = contextualizer
        self._worker_id = worker_id

    @property
    def _stage_names(self) -> list[str]:
        if self._contextualizer is None:
            return STAGE_NAMES
        names = list(STAGE_NAMES)
        names.insert(names.index("embed"), "contextualize")
        return names

    def run(self, run_id: UUID) -> None:
        """Execute the full ingestion pipeline for a single run.

        This method is synchronous/thread-friendly so both in-process dispatch
        and Temporal activity execution can call the same code.
        """
        claimed_run = try_claim_ingestion_run(run_id=run_id, worker_id=self._worker_id)
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
            # Document profile (loose|book) snapshotted on the run at upload —
            # selects the chunker (replaces the old source_type heuristic).
            profile = claimed_run.profile

            doc = session.scalar(select(Document).where(Document.id == document_id))
            object_key = doc.object_key if doc else ""
            content_type = "application/octet-stream"
            document_title = doc.title if doc else ""

        stages = ensure_ingestion_stages(run_id=run_id, tenant_id=tenant_id, stage_names=self._stage_names)
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
                    profile=profile,
                )
                if chunks is not None:
                    persist_chunks(
                        run_id=run_id,
                        document_id=document_id,
                        chunks=chunks,
                    )

            # Stage 3b: Contextualize (ADR-0020) — only present when a
            # contextualizer is injected; sets each leaf chunk's search prefix.
            if artifact is not None and self._contextualizer is not None:
                run_contextualize_stage(
                    run_id=run_id,
                    stage_id=stage_map["contextualize"].id,
                    document_id=document_id,
                    chunks=get_chunks_as_schemas(document_id=document_id),
                    contextualizer=self._contextualizer,
                    document_title=document_title,
                )

            # Stage 4: Embed
            embeddings = None
            if artifact is not None:
                db_chunks = get_chunks_as_schemas(document_id=document_id)
                embeddings = run_embed_stage(
                    run_id=run_id,
                    stage_id=stage_map["embed"].id,
                    chunks=db_chunks,
                    embedder=self._embedder,
                )

            acl_metadata = get_document_index_acl_metadata(document_id=document_id)

            # Stage 5: Index Qdrant
            if artifact is not None and embeddings is not None:
                db_chunks = get_chunks_as_schemas(document_id=document_id)
                run_index_qdrant_stage(
                    run_id=run_id,
                    stage_id=stage_map["index_qdrant"].id,
                    chunks=db_chunks,
                    embeddings=embeddings,
                    vector_indexer=self._vector_indexer,
                    acl_metadata=acl_metadata,
                )

            # Stage 6: Index OpenSearch
            if artifact is not None:
                db_chunks = get_chunks_as_schemas(document_id=document_id)
                run_index_opensearch_stage(
                    run_id=run_id,
                    stage_id=stage_map["index_opensearch"].id,
                    chunks=db_chunks,
                    lexical_indexer=self._lexical_indexer,
                    acl_metadata=acl_metadata,
                )

            # Stage 7: Quality report
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
