"""F1: book profile chunker.

Drives the BookDocumentChunker against synthetic ParsedArtifacts shaped like the
F0 adapter output (pages carrying rich `blocks` with block_type, heading_path
breadcrumb, and page anchors). Proves chapter→section→leaf grouping, breadcrumb
propagation, page anchors, atomic tables, parent/leaf linkage, and graceful
degradation for heading-less documents — all deterministic, no Docling models.
"""

from __future__ import annotations

from uuid import UUID

from app.schemas.chunks import DocumentProfile
from app.schemas.parsed_artifacts import (
    ParsedArtifact,
    ParsedBlock,
    ParsedPage,
    ParserProvenance,
)
from app.services.chunkers.book import BookDocumentChunker
from app.services.chunkers.factory import build_chunker
from app.services.chunkers.loose import LooseDocumentChunker

DOC_ID = "33333333-3333-3333-3333-333333333333"

_VELOCITY = "Velocity is the rate of change of position with respect to time, a vector quantity."
_ACCEL = "Acceleration is the rate of change of velocity with respect to time, also a vector."


def _block(block_type: str, text: str | None, heading_path: list[str], level: int | None = None) -> ParsedBlock:
    return ParsedBlock(block_type=block_type, text=text, heading_path=heading_path, level=level)


def _page(page_number: int, blocks: list[ParsedBlock]) -> ParsedPage:
    prose = "\n\n".join(b.text for b in blocks if b.text and b.block_type not in ("table", "picture", "chart"))
    return ParsedPage(page_number=page_number, text=prose, blocks=blocks)


def _artifact(pages: list[ParsedPage]) -> ParsedArtifact:
    return ParsedArtifact(
        document_id=UUID(DOC_ID),
        pages=pages,
        tables=[],
        provenance=ParserProvenance(
            parser_backend="docling-local", parser_version="2.102.1", profile="local-cpu"
        ),
    )


def _textbook_artifact() -> ParsedArtifact:
    ch = ["Introduction to Physics", "Chapter 1: Motion"]
    s11 = ch + ["1.1 Velocity"]
    s12 = ch + ["1.2 Acceleration"]
    page1 = _page(
        1,
        [
            _block("title", "Introduction to Physics", ["Introduction to Physics"], level=0),
            _block("section_header", "Chapter 1: Motion", ch, level=1),
            _block("section_header", "1.1 Velocity", s11, level=2),
            _block("text", _VELOCITY, s11),
        ],
    )
    page2 = _page(
        2,
        [
            _block("section_header", "1.2 Acceleration", s12, level=2),
            _block("text", _ACCEL, s12),
            _block("table", "| Quantity | Unit |\n| --- | --- |\n| Velocity | m/s |", s12),
        ],
    )
    return _artifact([page1, page2])


def test_groups_leaves_into_one_parent_per_section() -> None:
    chunks = BookDocumentChunker().chunk(_textbook_artifact(), profile=DocumentProfile.BOOK)

    parents = [c for c in chunks if c.parent_id is None]
    leaves = [c for c in chunks if c.parent_id is not None]

    # Two content-bearing sections (1.1, 1.2) → two parents.
    assert len(parents) == 2
    assert all(p.unit_type == "section" for p in parents)
    # 1.1 has one leaf; 1.2 has a paragraph + a table = two leaves.
    assert len(leaves) == 3

    by_section = {tuple(p.heading_path): p for p in parents}
    assert ("Introduction to Physics", "Chapter 1: Motion", "1.1 Velocity") in by_section
    assert ("Introduction to Physics", "Chapter 1: Motion", "1.2 Acceleration") in by_section


def test_leaves_link_to_their_section_parent_and_carry_breadcrumb() -> None:
    chunks = BookDocumentChunker().chunk(_textbook_artifact(), profile=DocumentProfile.BOOK)
    parents = {c.id: c for c in chunks if c.parent_id is None}

    velocity_leaf = next(
        c for c in chunks if c.parent_id is not None and c.text.startswith("Velocity is")
    )
    parent = parents[velocity_leaf.parent_id]
    # Leaf links to the section parent, and both carry the full chapter→section breadcrumb.
    assert parent.heading_path == ["Introduction to Physics", "Chapter 1: Motion", "1.1 Velocity"]
    assert velocity_leaf.heading_path == parent.heading_path
    assert velocity_leaf.unit_type == "paragraph"


def test_page_anchors_flow_through() -> None:
    chunks = BookDocumentChunker().chunk(_textbook_artifact(), profile=DocumentProfile.BOOK)

    velocity_leaf = next(
        c for c in chunks if c.parent_id is not None and c.text.startswith("Velocity is")
    )
    accel_leaf = next(
        c for c in chunks if c.parent_id is not None and c.text.startswith("Acceleration is")
    )
    assert (velocity_leaf.page_start, velocity_leaf.page_end) == (1, 1)
    assert (accel_leaf.page_start, accel_leaf.page_end) == (2, 2)

    # The 1.2 section parent spans only page 2 (its leaves are all on page 2).
    parents = {tuple(c.heading_path): c for c in chunks if c.parent_id is None}
    s12 = parents[("Introduction to Physics", "Chapter 1: Motion", "1.2 Acceleration")]
    assert (s12.page_start, s12.page_end) == (2, 2)


def test_tables_are_atomic_leaves() -> None:
    chunks = BookDocumentChunker().chunk(_textbook_artifact(), profile=DocumentProfile.BOOK)

    table_leaves = [c for c in chunks if c.unit_type == "table"]
    assert len(table_leaves) == 1
    table = table_leaves[0]
    assert "m/s" in table.text  # markdown preserved verbatim, not split
    assert table.heading_path == ["Introduction to Physics", "Chapter 1: Motion", "1.2 Acceleration"]
    assert table.parent_id is not None


def test_heading_blocks_are_not_emitted_as_leaves() -> None:
    chunks = BookDocumentChunker().chunk(_textbook_artifact(), profile=DocumentProfile.BOOK)
    # No chunk should be the bare heading text — headings define the breadcrumb only.
    texts = {c.text for c in chunks if c.parent_id is not None}
    assert "Chapter 1: Motion" not in texts
    assert "1.1 Velocity" not in texts


def test_chunk_indices_are_contiguous_and_parents_precede_children() -> None:
    chunks = BookDocumentChunker().chunk(_textbook_artifact(), profile=DocumentProfile.BOOK)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    # Each child's parent appears earlier in the list.
    seen_parent_ids: set = set()
    for c in chunks:
        if c.parent_id is None:
            seen_parent_ids.add(c.id)
        else:
            assert c.parent_id in seen_parent_ids


def test_headingless_document_degrades_to_single_section() -> None:
    artifact = _artifact([_page(1, [_block("text", _VELOCITY, []), _block("text", _ACCEL, [])])])
    chunks = BookDocumentChunker().chunk(artifact, profile=DocumentProfile.BOOK)

    parents = [c for c in chunks if c.parent_id is None]
    leaves = [c for c in chunks if c.parent_id is not None]
    assert len(parents) == 1
    assert parents[0].heading_path == []
    assert len(leaves) == 2


def test_short_prose_below_floor_is_skipped_but_tables_are_kept() -> None:
    artifact = _artifact(
        [
            _page(
                1,
                [
                    _block("text", "Too short.", ["S"]),  # < 64 chars → skipped
                    _block("table", "| a | b |\n| --- | --- |\n| 1 | 2 |", ["S"]),  # kept regardless of size
                ],
            )
        ]
    )
    chunks = BookDocumentChunker().chunk(artifact, profile=DocumentProfile.BOOK)
    leaves = [c for c in chunks if c.parent_id is not None]
    assert len(leaves) == 1
    assert leaves[0].unit_type == "table"


def test_empty_artifact_produces_no_chunks() -> None:
    assert BookDocumentChunker().chunk(_artifact([]), profile=DocumentProfile.BOOK) == []


def test_factory_routes_by_profile() -> None:
    assert isinstance(build_chunker(DocumentProfile.BOOK), BookDocumentChunker)
    assert isinstance(build_chunker(DocumentProfile.LOOSE), LooseDocumentChunker)
