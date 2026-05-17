from __future__ import annotations

import logging
from uuid import UUID

from app.repositories.ingestion import (
    get_stages_for_run,
    store_parsed_artifact,
    update_stage_status,
)
from app.schemas.parsed_artifacts import ParsedArtifact
from app.schemas.parsed_artifacts import OcrProvenance
from app.services.ocr import DoclingOcrService, OcrService
from app.services.parsers.base import DocumentParser, ParseRequest
from app.services.parsers.docling_backend import DoclingDocumentParser
from app.services.parsers.remote_backend import RemoteDocumentParser
from app.services.quality_report import build_quality_report

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
