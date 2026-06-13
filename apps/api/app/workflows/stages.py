from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.services.contextualizers.base import ChunkContextualizer

from app.repositories.ingestion import (
    get_stages_for_run,
    store_parsed_artifact,
    update_stage_status,
)
from app.schemas.parsed_artifacts import ParsedArtifact
from app.schemas.parsed_artifacts import OcrProvenance
from app.schemas.chunks import Chunk, DocumentProfile
from app.schemas.embeddings import EmbeddingResult
from app.services.ocr import DoclingOcrService, OcrService
from app.services.parsers.base import DocumentParser, ParseRequest
from app.services.parsers.docling_backend import DoclingDocumentParser
from app.services.parsers.remote_backend import RemoteDocumentParser
from app.services.quality_report import build_quality_report
from app.services.chunkers.factory import build_chunker
from app.services.embedders.base import Embedder
from app.services.indexers.base import VectorIndexer, LexicalIndexer

logger = logging.getLogger(__name__)


def _resolve_parser(parser_backend: str) -> DocumentParser:
    if parser_backend == "docling-local":
        return DoclingDocumentParser()
    if parser_backend == "remote-api":
        raise RuntimeError("Parser backend 'remote-api' requires an injected remote parser adapter.")
    raise ValueError(
        f"Unknown parser backend: {parser_backend}. Supported stage-local backends: docling-local, remote-api."
    )


def _resolve_ocr_service(*, parser_backend: str, ocr_service: OcrService | None) -> OcrService:
    if ocr_service is not None:
        return ocr_service

    if parser_backend == "remote-api":
        return DoclingOcrService(engine="remote-service", provider="remote-api")

    return DoclingOcrService(provider="docling-local")


def _is_stage_completed(*, run_id: UUID, stage_name: str) -> bool:
    stages = get_stages_for_run(run_id=run_id)
    for stage in stages:
        if stage.stage_name == stage_name and stage.status == "completed":
            return True
    return False


def run_parse_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    document_id: UUID,
    object_key: str,
    content_type: str,
    profile: str,
    parser_backend: str,
    parser: DocumentParser | None = None,
    ocr_service: OcrService | None = None,
    local_source_path: str | None = None,
) -> ParsedArtifact | None:
    """Run the parse stage. Returns None if stage was already completed (skipped)."""
    if _is_stage_completed(run_id=run_id, stage_name="parse"):
        logger.info("Stage parse already completed for run %s, skipping.", run_id)
        return None

    update_stage_status(stage_id=stage_id, status="running")

    if parser is None:
        parser = _resolve_parser(parser_backend)

    request = ParseRequest(
        document_id=str(document_id),
        object_key=object_key,
        content_type=content_type,
        profile=profile,
        parser_backend=parser_backend,
        local_source_path=local_source_path,
    )
    artifact = parser.parse(request)

    if artifact.provenance.ocr is not None:
        ocr_result = artifact.provenance.ocr
    else:
        ocr_result = _resolve_ocr_service(parser_backend=parser_backend, ocr_service=ocr_service).inspect(
            request=request,
            artifact=artifact,
        )
        artifact.provenance.ocr = OcrProvenance.model_validate(ocr_result.model_dump(mode="json"))

    update_stage_status(
        stage_id=stage_id,
        status="completed",
        details={
            "page_count": len(artifact.pages),
            "table_count": len(artifact.tables),
            "parser_backend": parser_backend,
            "parser_profile": profile,
            "ocr": {
                **ocr_result.model_dump(mode="json"),
                "page_count": len(ocr_result.page_numbers),
            },
        },
    )

    return artifact


def run_persist_artifact_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    artifact: ParsedArtifact,
) -> None:
    """Run the persist-artifact stage. No-op if already completed."""
    if _is_stage_completed(run_id=run_id, stage_name="persist_artifact"):
        logger.info("Stage persist_artifact already completed for run %s, skipping.", run_id)
        return

    update_stage_status(stage_id=stage_id, status="running")
    store_parsed_artifact(run_id=run_id, artifact=artifact)
    update_stage_status(stage_id=stage_id, status="completed")


def run_quality_report_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    artifact: ParsedArtifact,
) -> None:
    """Run the quality-report stage. No-op if already completed."""
    if _is_stage_completed(run_id=run_id, stage_name="quality_report"):
        logger.info("Stage quality_report already completed for run %s, skipping.", run_id)
        return

    update_stage_status(stage_id=stage_id, status="running")
    report = build_quality_report(artifact)
    update_stage_status(
        stage_id=stage_id,
        status="completed",
        details={
            "quality_score": report.quality_score,
            "warnings": report.warnings,
            "summary": report.summary,
            "counts": report.counts,
            "parser_backend": report.parser_backend,
            "parser_profile": report.parser_profile,
            "ocr": report.ocr,
        },
    )


def run_chunk_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    document_id: UUID,
    artifact: ParsedArtifact,
    source_type: str,
) -> list[Chunk] | None:
    """Run the chunk stage. Returns None if stage was already completed (skipped)."""
    if _is_stage_completed(run_id=run_id, stage_name="chunk"):
        logger.info("Stage chunk already completed for run %s, skipping.", run_id)
        return None

    update_stage_status(stage_id=stage_id, status="running")

    profile = DocumentProfile.LOOSE if source_type == "loose_document" else DocumentProfile.BOOK
    chunker = build_chunker(profile)
    chunks = chunker.chunk(artifact, profile=profile)

    # Ensure all chunks reference the actual document ID, not the artifact's
    # potentially-stale document_id (the parser may have used a placeholder).
    chunks = [
        chunk.model_copy(update={"document_id": document_id})
        for chunk in chunks
    ]

    update_stage_status(
        stage_id=stage_id,
        status="completed",
        details={
            "chunk_count": len(chunks),
            "leaf_count": sum(1 for c in chunks if c.parent_id is not None),
            "parent_count": sum(1 for c in chunks if c.parent_id is None),
            "profile": profile.value,
        },
    )

    return chunks


def run_contextualize_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    document_id: UUID,
    chunks: list[Chunk],
    contextualizer: "ChunkContextualizer",
    document_title: str,
) -> int | None:
    """Set each leaf chunk's situating context prefix (ADR-0020).

    Runs between ``chunk`` and ``embed`` only when contextual augmentation is
    enabled (the runner omits this stage entirely when disabled, keeping the
    pipeline byte-identical to the unaugmented path). Persists the prefix so
    downstream stages reload chunks whose ``search_text`` carries it. Returns
    None if already completed.
    """
    from app.repositories.chunks import set_chunk_context_prefixes
    from app.services.contextualizers.base import ContextualizeInput

    if _is_stage_completed(run_id=run_id, stage_name="contextualize"):
        logger.info("Stage contextualize already completed for run %s, skipping.", run_id)
        return None

    update_stage_status(stage_id=stage_id, status="running")

    leaf_chunks = [c for c in chunks if c.parent_id is not None]
    if not leaf_chunks:
        update_stage_status(stage_id=stage_id, status="completed", details={"contextualized_count": 0})
        return 0

    document_text = "\n\n".join(c.text for c in chunks if c.parent_id is None) or "\n\n".join(
        c.text for c in leaf_chunks
    )
    prefixes = contextualizer.contextualize(
        ContextualizeInput(
            document_title=document_title,
            document_text=document_text,
            leaf_chunks=leaf_chunks,
        )
    )
    typed_prefixes = {
        chunk.id: prefixes.get(chunk.id)
        for chunk in leaf_chunks
        if chunk.id is not None
    }
    updated = set_chunk_context_prefixes(prefixes=typed_prefixes)
    non_empty = sum(1 for v in typed_prefixes.values() if v)

    update_stage_status(
        stage_id=stage_id,
        status="completed",
        details={"contextualized_count": non_empty, "rows_updated": updated},
    )
    return non_empty


def run_embed_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    chunks: list[Chunk],
    embedder: Embedder,
) -> list[EmbeddingResult] | None:
    """Run the embed stage. Returns None if already completed."""
    if _is_stage_completed(run_id=run_id, stage_name="embed"):
        logger.info("Stage embed already completed for run %s, skipping.", run_id)
        return None

    update_stage_status(stage_id=stage_id, status="running")

    # Only embed leaf chunks (children) — parents are not independently embedded
    leaf_chunks = [c for c in chunks if c.parent_id is not None]
    if not leaf_chunks:
        update_stage_status(stage_id=stage_id, status="completed", details={"embedding_count": 0})
        return []

    chunk_ids = []
    for chunk in leaf_chunks:
        if chunk.id is None:
            raise RuntimeError(
                "Chunk embedding requires persisted chunk IDs. Re-run chunk persistence before embedding."
            )
        chunk_ids.append(chunk.id)
    # search_text == text when unaugmented (ADR-0020); the augmented prefix
    # enriches the embedding without changing the stored display text.
    texts = [c.search_text for c in leaf_chunks]
    results = embedder.embed(chunk_ids=chunk_ids, texts=texts)

    update_stage_status(
        stage_id=stage_id,
        status="completed",
        details={
            "embedding_count": len(results),
            "leaf_count": len(leaf_chunks),
        },
    )

    return results


def run_index_qdrant_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    chunks: list[Chunk],
    embeddings: list[EmbeddingResult],
    vector_indexer: VectorIndexer,
    acl_metadata: dict,
) -> None:
    """Run the Qdrant index stage. No-op if already completed."""
    if _is_stage_completed(run_id=run_id, stage_name="index_qdrant"):
        logger.info("Stage index_qdrant already completed for run %s, skipping.", run_id)
        return

    update_stage_status(stage_id=stage_id, status="running")

    leaf_chunks = [c for c in chunks if c.parent_id is not None]
    count = vector_indexer.upsert(chunks=leaf_chunks, embeddings=embeddings, acl_metadata=acl_metadata)

    update_stage_status(
        stage_id=stage_id,
        status="completed",
        details={"upserted_count": count},
    )


def run_index_opensearch_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    chunks: list[Chunk],
    lexical_indexer: LexicalIndexer,
    acl_metadata: dict,
) -> None:
    """Run the OpenSearch index stage. No-op if already completed."""
    if _is_stage_completed(run_id=run_id, stage_name="index_opensearch"):
        logger.info("Stage index_opensearch already completed for run %s, skipping.", run_id)
        return

    update_stage_status(stage_id=stage_id, status="running")

    leaf_chunks = [c for c in chunks if c.parent_id is not None]
    count = lexical_indexer.upsert(chunks=leaf_chunks, acl_metadata=acl_metadata)

    update_stage_status(
        stage_id=stage_id,
        status="completed",
        details={"upserted_count": count},
    )
