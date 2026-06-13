from __future__ import annotations

import textwrap
from typing import Literal
from typing import cast
from uuid import UUID

import pytest

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


@pytest.mark.slow
def test_real_docling_convert_surfaces_hierarchy(tmp_path) -> None:
    """F0: exercise the REAL DocumentConverter().convert() path (no injected
    converter) end-to-end through the adapter, proving Docling is installed and
    the adapter surfaces heading hierarchy + breadcrumbs from real output.

    Uses a Markdown fixture: Docling's Markdown backend is rule-based and maps
    `#`/`##`/`###` to title/section_header items deterministically, so the test
    proves the hierarchy walk without depending on a vision model classifying a
    hand-authored PDF. Page anchors are exercised against real PDFs in F1.
    """
    pytest.importorskip("docling", reason="docling not installed (install [ingestion] extras)")

    source = tmp_path / "physics_excerpt.md"
    source.write_text(
        textwrap.dedent(
            """\
            # Introduction to Physics

            ## Chapter 1: Motion

            ### 1.1 Velocity

            Velocity is the rate of change of position with respect to time.

            ### 1.2 Acceleration

            Acceleration is the rate of change of velocity.
            """
        )
    )

    parser = DoclingDocumentParser()  # real DocumentConverter, no injected converter
    artifact = parser.parse(
        ParseRequest(
            document_id="22222222-2222-2222-2222-222222222222",
            object_key="documents/physics_excerpt.md",
            content_type="text/markdown",
            profile="local-cpu",
            local_source_path=str(source),
        )
    )

    # Real Docling produced section headers; the adapter turned them into a
    # chapter -> section breadcrumb on the leaf paragraph.
    para = _find_block(artifact, "Velocity is the rate of change")
    assert para.block_type == "text"
    assert para.heading_path == [
        "Introduction to Physics",
        "Chapter 1: Motion",
        "1.1 Velocity",
    ]
    # Same-depth header truncation works on real output too.
    para2 = _find_block(artifact, "Acceleration is the rate of change")
    assert para2.heading_path[-1] == "1.2 Acceleration"
    # Version resolved from the installed package (proves Docling really ran).
    assert artifact.provenance.parser_version != "unknown"


def _find_block(artifact: ParsedArtifact, text_prefix: str):
    for page in artifact.pages:
        for block in page.blocks:
            if block.text and block.text.startswith(text_prefix):
                return block
    raise AssertionError(f"no block starting with {text_prefix!r}")
