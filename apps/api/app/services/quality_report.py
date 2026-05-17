from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from app.schemas.parsed_artifacts import ParsedArtifact


def _default_ocr_identity(parser_backend: str) -> tuple[str, str]:
    if parser_backend == "remote-api":
        return "remote-service", "remote-api"

    return "tesseract", "docling-local"


class QualityReportSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_score: float
    parser_backend: str
    parser_version: str
    parser_profile: str
    summary: dict[str, int]
    counts: dict[str, int]
    warnings: list[str]
    ocr: dict[str, object]
    raw_payload: str

    @property
    def page_count(self) -> int:
        return self.summary["page_count"]

    @property
    def table_count(self) -> int:
        return self.summary["table_count"]


def build_quality_report(artifact: ParsedArtifact) -> QualityReportSummary:
    page_count = len(artifact.pages)
    table_count = len(artifact.tables)
    non_empty_text_pages = sum(1 for page in artifact.pages if page.text.strip())
    empty_text_pages = page_count - non_empty_text_pages
    block_count = sum(len(page.blocks) for page in artifact.pages)
    table_pages = len({table.page_number for table in artifact.tables})
    quality_score = 0.0 if page_count == 0 else non_empty_text_pages / page_count
    warnings: list[str] = []
    ocr = artifact.provenance.ocr
    ocr_page_numbers = list(ocr.page_numbers) if ocr is not None else []

    if non_empty_text_pages != page_count:
        warnings.append("Some pages do not contain extractable text.")

    if ocr is not None and ocr.status == "applied":
        warnings.append(f"OCR was applied to {len(ocr_page_numbers)} page(s).")
    elif ocr is not None and ocr.status == "unverified":
        warnings.append("OCR usage could not yet be verified from the parser runtime output.")

    counts = {
        "page_count": page_count,
        "table_count": table_count,
        "non_empty_text_pages": non_empty_text_pages,
        "empty_text_pages": empty_text_pages,
        "block_count": block_count,
        "table_page_count": table_pages,
        "ocr_page_count": len(ocr_page_numbers),
    }
    default_engine, default_provider = _default_ocr_identity(artifact.provenance.parser_backend)
    ocr_payload = {
        "status": ocr.status if ocr is not None else "unverified",
        "applied": ocr.applied if ocr is not None else None,
        "engine": ocr.engine if ocr is not None else default_engine,
        "provider": ocr.provider if ocr is not None else default_provider,
        "page_numbers": ocr_page_numbers,
        "page_count": len(ocr_page_numbers),
        "notes": list(ocr.notes) if ocr is not None else [],
    }
    raw_payload = json.dumps(
        {
            "quality_score": quality_score,
            "parser_backend": artifact.provenance.parser_backend,
            "parser_version": artifact.provenance.parser_version,
            "parser_profile": artifact.provenance.profile,
            "counts": counts,
            "warnings": warnings,
            "ocr": ocr_payload,
        },
        separators=(",", ":"),
        sort_keys=True,
    )

    return QualityReportSummary(
        quality_score=quality_score,
        parser_backend=artifact.provenance.parser_backend,
        parser_version=artifact.provenance.parser_version,
        parser_profile=artifact.provenance.profile,
        summary=counts,
        counts=counts,
        warnings=warnings,
        ocr=ocr_payload,
        raw_payload=raw_payload,
    )
