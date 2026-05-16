from __future__ import annotations

from uuid import UUID

from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance
from app.services.quality_report import build_quality_report


def test_build_quality_report_summarizes_page_table_and_text_coverage() -> None:
    artifact = ParsedArtifact(
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        pages=[
            ParsedPage(page_number=1, text="hello world", blocks=[]),
            ParsedPage(page_number=2, text="", blocks=[]),
        ],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 100, 100], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="docling", parser_version="2.x", profile="gpu-local"),
    )

    report = build_quality_report(artifact)

    assert report.summary["page_count"] == 2
    assert report.summary["table_count"] == 1
    assert report.summary["non_empty_text_pages"] == 1
    assert report.quality_score == 0.5
