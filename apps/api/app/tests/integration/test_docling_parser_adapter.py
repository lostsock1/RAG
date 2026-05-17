from __future__ import annotations

from typing import Literal
from typing import cast
from uuid import UUID

from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance
from app.services.parsers.base import ParseRequest
from app.services.parsers.docling_backend import DoclingDocumentParser

CanonicalProfile = Literal["local-cpu", "local-gpu", "remote-api"]


def test_docling_parser_returns_normalized_artifact_from_injected_converter() -> None:
    parser = DoclingDocumentParser(
        converter=lambda request: ParsedArtifact(
            document_id=UUID(request.document_id),
            pages=[ParsedPage(page_number=1, text="Converted", blocks=[])],
            tables=[ParsedTable(page_number=1, bbox=[0, 0, 1, 1], markdown="|a|b|")],
            provenance=ParserProvenance(
                parser_backend="docling-local",
                parser_version="2.x",
                profile=cast(CanonicalProfile, request.profile),
            ),
        )
    )

    artifact = parser.parse(
        ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/sample.pdf",
            content_type="application/pdf",
            profile="local-gpu",
            parser_backend="docling-local",
        )
    )

    assert artifact.provenance.parser_backend == "docling-local"
    assert artifact.pages[0].text == "Converted"
