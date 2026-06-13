from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Literal
from typing import cast
from uuid import UUID

import pytest

from app.schemas.chunks import DocumentProfile
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance
from app.services.chunkers.factory import build_chunker
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


@pytest.mark.slow
def test_real_docling_book_profile_chunks_into_sections(tmp_path) -> None:
    """F1 e2e: real DocumentConverter().convert() → BookDocumentChunker. Proves the
    parse→chunk handoff turns genuine Docling output into a multi-parent section
    tree with chapter→section breadcrumbs and an atomic table leaf. (Multi-parent
    *persistence* is covered by test_chunks_repository; page anchors by
    test_book_chunker — a Markdown fixture is pageless but deterministically
    structured, which is what this test needs.)"""
    pytest.importorskip("docling", reason="docling not installed (install [ingestion] extras)")

    source = tmp_path / "physics_primer.md"
    source.write_text(
        textwrap.dedent(
            """\
            # Physics Primer

            ## Chapter 1: Kinematics

            ### 1.1 Velocity

            Velocity is the rate of change of position with respect to time, a vector quantity with direction.

            ### 1.2 Acceleration

            Acceleration is the rate of change of velocity with respect to time, also a vector quantity.

            | Quantity | Unit |
            | --- | --- |
            | Velocity | m/s |
            | Acceleration | m/s^2 |

            ## Chapter 2: Dynamics

            ### 2.1 Newton's First Law

            An object in motion stays in motion unless acted upon by an external net force, per inertia.
            """
        )
    )

    artifact = DoclingDocumentParser().parse(
        ParseRequest(
            document_id="44444444-4444-4444-4444-444444444444",
            object_key="documents/physics_primer.md",
            content_type="text/markdown",
            profile="local-cpu",
            local_source_path=str(source),
        )
    )
    chunks = build_chunker(DocumentProfile.BOOK).chunk(artifact, profile=DocumentProfile.BOOK)

    parents = [c for c in chunks if c.parent_id is None]
    leaves = [c for c in chunks if c.parent_id is not None]
    parent_ids = {p.id for p in parents}

    # Three sections (1.1, 1.2, 2.1) → three section parents (multi-parent).
    assert len(parents) == 3
    assert all(p.unit_type == "section" for p in parents)
    # Every leaf links to a real section parent.
    assert leaves and all(leaf.parent_id in parent_ids for leaf in leaves)

    velocity = next(c for c in leaves if c.text.startswith("Velocity is"))
    assert velocity.heading_path == ["Physics Primer", "Chapter 1: Kinematics", "1.1 Velocity"]

    # The GFM table became an atomic table leaf under 1.2 Acceleration.
    table = next(c for c in leaves if c.unit_type == "table")
    assert "m/s" in table.text
    assert table.heading_path == ["Physics Primer", "Chapter 1: Kinematics", "1.2 Acceleration"]


@pytest.mark.slow
def test_real_docling_pdf_book_profile_carries_page_anchors() -> None:
    """F2.4 e2e: real DocumentConverter().convert() on a committed two-page
    textbook **PDF** -> BookDocumentChunker, proving per-item page anchors
    (Docling ``prov[0].page_no``) flow through into chunk ``page_start``/
    ``page_end``. This is the one thing the pageless Markdown e2e fixtures
    cannot exercise (their single page is always page 1).

    Real-Docling PDF behavior pinned here (differs from the rule-based Markdown
    backend): the layout model labels every detected heading as a generic
    ``section_header`` at ``level=1`` — it infers no heading *depth* from font
    size — so heading_paths come out **flat** (one section per heading) rather
    than as nested chapter->section breadcrumbs. Nested-breadcrumb depth is
    covered by the Markdown e2e + synthetic-block unit tests; this test owns the
    page-anchor guarantee. (Docling also runs its default layout+OCR pipeline on
    the PDF, so this is a heavier, network-touching slow test.)

    Fixture is committed (``fixtures/textbook_excerpt.pdf``); regenerate via
    ``fixtures/generate_textbook_pdf.py``. Subject (music theory) is disjoint
    from the eval heldout subjects, so it is span-isolation-safe.
    """
    pytest.importorskip("docling", reason="docling not installed (install [ingestion] extras)")

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "textbook_excerpt.pdf"
    assert fixture.exists(), f"missing committed PDF fixture: {fixture}"

    artifact = DoclingDocumentParser().parse(
        ParseRequest(
            document_id="55555555-5555-5555-5555-555555555555",
            object_key="documents/textbook_excerpt.pdf",
            content_type="application/pdf",
            profile="local-cpu",
            local_source_path=str(fixture),
        )
    )
    # The PDF genuinely has two physical pages.
    assert {p.page_number for p in artifact.pages} == {1, 2}

    chunks = build_chunker(DocumentProfile.BOOK).chunk(artifact, profile=DocumentProfile.BOOK)
    leaves = [c for c in chunks if c.parent_id is not None]
    # Docling detected the headings -> the book chunker built real section parents.
    section_parents = [c for c in chunks if c.parent_id is None and c.unit_type == "section"]
    assert len(section_parents) >= 2

    def _page_of(text_prefix: str) -> tuple[int | None, int | None]:
        matches = [c for c in leaves if c.text.startswith(text_prefix)]
        assert matches, f"no leaf starting with {text_prefix!r}"
        pages = {(c.page_start, c.page_end) for c in matches}
        assert len(pages) == 1, f"leaves for {text_prefix!r} span multiple pages: {pages}"
        return next(iter(pages))

    # Chapter 1's two sections live on page 1; Chapter 2's on page 2.
    assert _page_of("The staff consists of five") == (1, 1)
    assert _page_of("An accidental is a symbol") == (1, 1)
    assert _page_of("In common time a whole note") == (2, 2)
    assert _page_of("A time signature is written") == (2, 2)

    # No leaf leaked a null anchor.
    assert all(c.page_start is not None and c.page_end is not None for c in leaves)


def _find_block(artifact: ParsedArtifact, text_prefix: str):
    for page in artifact.pages:
        for block in page.blocks:
            if block.text and block.text.startswith(text_prefix):
                return block
    raise AssertionError(f"no block starting with {text_prefix!r}")
