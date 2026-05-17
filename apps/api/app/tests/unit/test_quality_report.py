from __future__ import annotations

import json
from uuid import UUID

from app.schemas.parsed_artifacts import OcrProvenance, ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance
from app.services.quality_report import build_quality_report


def test_build_quality_report_summarizes_page_table_and_text_coverage() -> None:
    artifact = ParsedArtifact(
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        pages=[
            ParsedPage(page_number=1, text="hello world", blocks=[]),
            ParsedPage(page_number=2, text="", blocks=[]),
        ],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 100, 100], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="docling-local", parser_version="2.x", profile="local-gpu"),
    )

    report = build_quality_report(artifact)

    assert report.summary["page_count"] == 2
    assert report.summary["table_count"] == 1
    assert report.summary["non_empty_text_pages"] == 1
    assert report.quality_score == 0.5
    assert report.ocr["status"] == "unverified"
    assert report.ocr["applied"] is None


def test_build_quality_report_includes_parser_and_ocr_contract_fields() -> None:
    artifact = ParsedArtifact(
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        pages=[
            ParsedPage(page_number=1, text="hello world", blocks=[]),
            ParsedPage(page_number=2, text="", blocks=[]),
        ],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 100, 100], markdown="|a|b|")],
        provenance=ParserProvenance(
            parser_backend="docling-local",
            parser_version="2.x",
            profile="local-gpu",
            ocr=OcrProvenance(
                applied=True,
                engine="tesseract",
                provider="docling-local",
                status="applied",
                page_numbers=[2],
                notes=["ocr used for scanned page detection"],
            ),
        ),
    )

    report = build_quality_report(artifact)

    assert report.parser_backend == "docling-local"
    assert report.parser_version == "2.x"
    assert report.parser_profile == "local-gpu"
    assert report.counts["empty_text_pages"] == 1
    assert report.counts["ocr_page_count"] == 1
    assert report.ocr["status"] == "applied"
    assert report.ocr["applied"] is True
    assert report.ocr["engine"] == "tesseract"
    assert report.ocr["provider"] == "docling-local"

    raw_payload = json.loads(report.raw_payload)
    assert raw_payload["parser_profile"] == "local-gpu"
    assert raw_payload["ocr"]["page_numbers"] == [2]
