from __future__ import annotations

from uuid import UUID

from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance


def test_parsed_artifact_requires_pages_tables_and_provenance() -> None:
    artifact = ParsedArtifact(
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        pages=[ParsedPage(page_number=1, text="Example", blocks=[])],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 100, 100], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="docling", parser_version="2.x", profile="gpu-local"),
    )

    assert artifact.tables[0].markdown.startswith("|a|")


def test_parsed_artifact_uses_four_point_bounding_boxes() -> None:
    artifact = ParsedArtifact(
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        pages=[ParsedPage(page_number=1, text="Example", blocks=[])],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 100, 100], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="docling", parser_version="2.x", profile="gpu-local"),
    )

    assert artifact.tables[0].bbox == [0.0, 0.0, 100.0, 100.0]
