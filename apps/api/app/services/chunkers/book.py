from __future__ import annotations

import logging
from uuid import uuid4

from app.schemas.chunks import Chunk, DocumentProfile
from app.schemas.parsed_artifacts import ParsedArtifact

logger = logging.getLogger(__name__)

# Target sizes per ADR-0012, shared with the loose profile for consistency.
LEAF_MAX_CHARS = 2048  # ~512 tokens at ~4 chars/token
LEAF_MIN_CHARS = 64
PARENT_MAX_CHARS = 8192  # ~2048 tokens

# Block types that define structure rather than citable content.
_HEADING_TYPES = frozenset({"title", "section_header"})
# Block types with no chunkable text (figures); skipped as leaves.
_FIGURE_TYPES = frozenset({"picture", "chart"})


class BookDocumentChunker:
    """Hierarchy-aware chunker for the book profile (ADR-0012).

    Consumes the structured ``blocks`` the Docling adapter produces (F0): every
    block carries a ``heading_path`` breadcrumb (chapter → section → …) and a
    page anchor. Produces a two-level chunk tree — one parent chunk per
    content-bearing section, with that section's paragraphs/tables/formulas as
    leaves. Every chunk carries the full heading-path breadcrumb, so the
    chapter/section context survives into retrieval, citations, and E2 breadcrumb
    augmentation; page anchors flow into ``page_start``/``page_end`` so citations
    gain page numbers. Tables are atomic (never split). Deterministic.

    The chunk tree is intentionally two-level (section-parent → leaves) to fit the
    existing ``Chunk`` model and parent-child expansion; the full chapter→section
    hierarchy is preserved semantically in ``heading_path`` rather than as a deep
    chain of parent chunks. Documents with no detected headings degrade to a
    single section keyed on the empty breadcrumb (loose-like).
    """

    def chunk(
        self,
        artifact: ParsedArtifact,
        *,
        profile: DocumentProfile,
    ) -> list[Chunk]:
        # Group leaf units by their section breadcrumb, preserving first-seen
        # reading order (pages are page-sorted by the adapter; blocks are in
        # reading order within each page).
        order: list[tuple[str, ...]] = []
        groups: dict[tuple[str, ...], list[_LeafUnit]] = {}

        for page in artifact.pages:
            for block in page.blocks:
                block_type = block.block_type or "text"
                if block_type in _HEADING_TYPES or block_type in _FIGURE_TYPES:
                    continue
                text = (block.text or "").strip()
                if not text:
                    continue
                is_table = block_type == "table"
                # Tables are atomic regardless of size; prose leaves respect the
                # min-size floor.
                if not is_table and len(text) < LEAF_MIN_CHARS:
                    continue

                section_key = tuple(block.heading_path)
                if section_key not in groups:
                    groups[section_key] = []
                    order.append(section_key)

                page_no = page.page_number
                if is_table:
                    groups[section_key].append(
                        _LeafUnit(text=text, unit_type="table", page_start=page_no, page_end=page_no)
                    )
                else:
                    for piece in _split_oversized(text):
                        groups[section_key].append(
                            _LeafUnit(
                                text=piece,
                                unit_type=_leaf_unit_type(block_type),
                                page_start=page_no,
                                page_end=page_no,
                            )
                        )

        chunks: list[Chunk] = []
        chunk_index = 0
        document_id = artifact.document_id

        for section_key in order:
            leaves = groups[section_key]
            if not leaves:
                continue
            heading_path = list(section_key)

            # Parent chunk for the section. Its id is the linkage key the leaves
            # reference and persistence resolves to a DB id (multi-parent safe).
            parent_text = "\n\n".join(unit.text for unit in leaves)
            if len(parent_text) > PARENT_MAX_CHARS:
                parent_text = parent_text[:PARENT_MAX_CHARS]
            parent_id = uuid4()
            chunks.append(
                Chunk(
                    id=parent_id,
                    document_id=document_id,
                    unit_type="section",
                    heading_path=heading_path,
                    page_start=min(unit.page_start for unit in leaves),
                    page_end=max(unit.page_end for unit in leaves),
                    text=parent_text,
                    parent_id=None,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1

            for unit in leaves:
                chunks.append(
                    Chunk(
                        document_id=document_id,
                        unit_type=unit.unit_type,
                        heading_path=heading_path,
                        page_start=unit.page_start,
                        page_end=unit.page_end,
                        text=unit.text,
                        parent_id=parent_id,
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1

        return chunks


class _LeafUnit:
    __slots__ = ("text", "unit_type", "page_start", "page_end")

    def __init__(self, *, text: str, unit_type: str, page_start: int, page_end: int) -> None:
        self.text = text
        self.unit_type = unit_type
        self.page_start = page_start
        self.page_end = page_end


def _leaf_unit_type(block_type: str) -> str:
    if block_type in ("text", "paragraph"):
        return "paragraph"
    return block_type


def _split_oversized(text: str) -> list[str]:
    """Split text longer than LEAF_MAX_CHARS on whitespace boundaries."""
    if len(text) <= LEAF_MAX_CHARS:
        return [text]
    pieces: list[str] = []
    remaining = text
    while len(remaining) > LEAF_MAX_CHARS:
        cut = remaining.rfind(" ", 0, LEAF_MAX_CHARS)
        if cut <= 0:
            cut = LEAF_MAX_CHARS
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return [piece for piece in pieces if piece]
