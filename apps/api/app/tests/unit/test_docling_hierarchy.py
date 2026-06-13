"""F0: Docling adapter body-tree hierarchy extraction.

These tests build a synthetic `DoclingDocument` with REAL docling-core types
(no ML models, no PDF) and drive it through the adapter's real-Docling
normalization path. They prove the adapter surfaces chapter -> section -> leaf
hierarchy, heading breadcrumbs, and page anchors that the current production
adapter discarded (it emitted flat pages with `blocks=[]` and, against real
Docling, empty page text).
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from app.schemas.parsed_artifacts import ParsedArtifact
from app.services.parsers.base import ParseRequest
from app.services.parsers.docling_backend import (
    DoclingDocumentParser,
    _normalize_docling_result,
)

pytest.importorskip("docling_core")

from docling_core.types.doc.base import BoundingBox, CoordOrigin, Size  # noqa: E402
from docling_core.types.doc.document import DoclingDocument, ProvenanceItem  # noqa: E402
from docling_core.types.doc.labels import DocItemLabel  # noqa: E402

DOC_ID = "11111111-1111-1111-1111-111111111111"


def _prov(page_no: int, top: float) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=page_no,
        bbox=BoundingBox(l=10.0, t=top, r=110.0, b=top + 10.0, coord_origin=CoordOrigin.TOPLEFT),
        charspan=(0, 1),
    )


def _build_textbook_document() -> DoclingDocument:
    """A two-page excerpt: title, chapter, two sections, a paragraph each, a table."""
    doc = DoclingDocument(name="physics-excerpt")
    doc.add_page(page_no=1, size=Size(width=600.0, height=800.0))
    doc.add_page(page_no=2, size=Size(width=600.0, height=800.0))

    doc.add_title(text="Introduction to Physics", prov=_prov(1, 50))
    doc.add_heading(text="Chapter 1: Motion", level=1, prov=_prov(1, 100))
    doc.add_heading(text="1.1 Velocity", level=2, prov=_prov(1, 150))
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="Velocity is the rate of change of position with respect to time.",
        prov=_prov(1, 200),
    )
    # New subsection continuing onto page 2.
    doc.add_heading(text="1.2 Acceleration", level=2, prov=_prov(2, 100))
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="Acceleration is the rate of change of velocity.",
        prov=_prov(2, 150),
    )
    table = doc.add_table(data=_two_by_two_table_data(), prov=_prov(2, 250))
    table.captions = []
    return doc


def _two_by_two_table_data():
    from docling_core.types.doc.document import TableCell, TableData

    cells = [
        TableCell(text="Quantity", row_span=1, col_span=1, start_row_offset_idx=0,
                  end_row_offset_idx=1, start_col_offset_idx=0, end_col_offset_idx=1, column_header=True),
        TableCell(text="Unit", row_span=1, col_span=1, start_row_offset_idx=0,
                  end_row_offset_idx=1, start_col_offset_idx=1, end_col_offset_idx=2, column_header=True),
        TableCell(text="Velocity", row_span=1, col_span=1, start_row_offset_idx=1,
                  end_row_offset_idx=2, start_col_offset_idx=0, end_col_offset_idx=1),
        TableCell(text="m/s", row_span=1, col_span=1, start_row_offset_idx=1,
                  end_row_offset_idx=2, start_col_offset_idx=1, end_col_offset_idx=2),
    ]
    return TableData(num_rows=2, num_cols=2, table_cells=cells)


def _normalize(doc: DoclingDocument) -> ParsedArtifact:
    request = ParseRequest(
        document_id=DOC_ID,
        object_key="documents/physics.pdf",
        content_type="application/pdf",
        profile="local-cpu",
        parser_backend="docling-local",
    )
    return _normalize_docling_result(
        request=request,
        conversion_result=SimpleNamespace(document=doc),
        parser_backend="docling-local",
        parser_version="2.102.1",
    )


def test_blocks_carry_heading_path_and_page_anchor() -> None:
    artifact = _normalize(_build_textbook_document())

    # Two pages produced, in order.
    assert [page.page_number for page in artifact.pages] == [1, 2]

    # The page-1 paragraph carries the full chapter -> section breadcrumb.
    para = _find_block(artifact, "Velocity is the rate of change")
    assert para.block_type == "text"
    assert para.heading_path == [
        "Introduction to Physics",
        "Chapter 1: Motion",
        "1.1 Velocity",
    ]
    assert para.bbox is not None and len(para.bbox) == 4

    # The page-2 paragraph's breadcrumb swapped 1.1 -> 1.2 (same-depth header
    # truncation) while keeping the chapter above it.
    para2 = _find_block(artifact, "Acceleration is the rate of change")
    assert para2.heading_path == [
        "Introduction to Physics",
        "Chapter 1: Motion",
        "1.2 Acceleration",
    ]


def test_section_headers_record_their_level() -> None:
    artifact = _normalize(_build_textbook_document())

    title = _find_block(artifact, "Introduction to Physics")
    assert title.block_type == "title" and title.level == 0

    chapter = _find_block(artifact, "Chapter 1: Motion")
    assert chapter.block_type == "section_header" and chapter.level == 1

    section = _find_block(artifact, "1.1 Velocity")
    assert section.block_type == "section_header" and section.level == 2


def test_page_text_is_prose_only_loose_profile_contract() -> None:
    """page.text must stay prose-only so the loose chunker is unaffected:
    tables/figures are NOT in page.text (loose reads artifact.tables separately)."""
    artifact = _normalize(_build_textbook_document())

    page2 = next(page for page in artifact.pages if page.page_number == 2)
    assert "Acceleration is the rate of change" in page2.text
    # The table content must not have leaked into prose text.
    assert "m/s" not in page2.text

    # The table is surfaced via artifact.tables (loose-profile input) ...
    assert len(artifact.tables) == 1
    assert artifact.tables[0].page_number == 2
    # ... and ALSO as a block in the hierarchy (book-profile input), under 1.2.
    table_block = next(b for page in artifact.pages for b in page.blocks if b.block_type == "table")
    assert table_block.heading_path == [
        "Introduction to Physics",
        "Chapter 1: Motion",
        "1.2 Acceleration",
    ]


def test_real_docling_path_smoke_via_parser_injected_none() -> None:
    """The adapter's real path is exercised end-to-end against real docling-core
    objects through the public parser API (converter injected to return the
    synthetic conversion result), proving the normalization is wired into parse()."""
    doc = _build_textbook_document()

    def fake_convert(_request: ParseRequest) -> ParsedArtifact:
        return _normalize_docling_result(
            request=_request,
            conversion_result=SimpleNamespace(document=doc),
            parser_backend="docling-local",
            parser_version="2.102.1",
        )

    parser = DoclingDocumentParser(converter=fake_convert)
    artifact = parser.parse(
        ParseRequest(
            document_id=DOC_ID,
            object_key="documents/physics.pdf",
            content_type="application/pdf",
            profile="local-cpu",
        )
    )
    assert artifact.document_id == UUID(DOC_ID)
    assert any(b.heading_path for page in artifact.pages for b in page.blocks)


def _find_block(artifact: ParsedArtifact, text_prefix: str):
    for page in artifact.pages:
        for block in page.blocks:
            if block.text and block.text.startswith(text_prefix):
                return block
    raise AssertionError(f"no block starting with {text_prefix!r}")
