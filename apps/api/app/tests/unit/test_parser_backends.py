from __future__ import annotations

from uuid import UUID

import pytest

from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance
from app.services.parsers.base import ParseRequest
from app.services.parsers.docling_backend import DoclingDocumentParser
from app.services.parsers.remote_backend import RemoteDocumentParser


def _build_artifact(*, profile: str = "source-profile") -> ParsedArtifact:
    return ParsedArtifact(
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        pages=[ParsedPage(page_number=1, text="Example", blocks=[])],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 1, 1], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="stub", parser_version="1.0", profile=profile),
    )


def test_remote_document_parser_overrides_profile_from_request() -> None:
    parser = RemoteDocumentParser(invoke_remote_parser=lambda request: _build_artifact())

    artifact = parser.parse(
        ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/sample.txt",
            content_type="text/plain",
            profile="gpu-local",
        )
    )

    assert artifact.provenance.parser_backend == "remote"
    assert artifact.provenance.profile == "gpu-local"


def test_docling_document_parser_requires_configured_converter() -> None:
    parser = DoclingDocumentParser()

    with pytest.raises(RuntimeError) as exc_info:
        parser.parse(
            ParseRequest(
                document_id="11111111-1111-1111-1111-111111111111",
                object_key="documents/sample.pdf",
                content_type="application/pdf",
                profile="cpu-local",
            )
        )

    assert "Docling parsing is not configured" in str(exc_info.value)
