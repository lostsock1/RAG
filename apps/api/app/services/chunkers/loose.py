from __future__ import annotations

import logging
from uuid import uuid4

from app.schemas.chunks import Chunk, DocumentProfile
from app.schemas.parsed_artifacts import ParsedArtifact

logger = logging.getLogger(__name__)

# Target sizes per ADR-0012
LEAF_MAX_CHARS = 2048  # ~512 tokens at ~4 chars/token
LEAF_MIN_CHARS = 64
PARENT_MAX_CHARS = 8192  # ~2048 tokens


class LooseDocumentChunker:
    """Structure-aware chunker for loose documents.

    Strategy:
    - Each page's text is split on paragraph boundaries (double newline).
    - Each table is its own atomic chunk.
    - A single parent chunk wraps the entire document for flat documents.
    - Heading path is empty for flat loose docs (no structural headings detected).
    """

    def chunk(
        self,
        artifact: ParsedArtifact,
        *,
        profile: DocumentProfile,
    ) -> list[Chunk]:
        if not artifact.pages and not artifact.tables:
            return []

        document_id = artifact.document_id
        chunk_index = 0

        # Collect all leaf units first
        leaf_units: list[_LeafUnit] = []

        for page in artifact.pages:
            paragraphs = _split_paragraphs(page.text)
            for para in paragraphs:
                stripped = para.strip()
                if len(stripped) < LEAF_MIN_CHARS:
                    continue
                leaf_units.append(
                    _LeafUnit(
                        text=stripped,
                        unit_type="paragraph",
                        page_start=page.page_number,
                        page_end=page.page_number,
                    )
                )

        for table in artifact.tables:
            leaf_units.append(
                _LeafUnit(
                    text=table.markdown,
                    unit_type="table",
                    page_start=table.page_number,
                    page_end=table.page_number,
                )
            )

        if not leaf_units:
            return []

        # Create a single parent chunk for the flat document
        parent_text = "\n\n".join(unit.text for unit in leaf_units)
        if len(parent_text) > PARENT_MAX_CHARS:
            parent_text = parent_text[:PARENT_MAX_CHARS]

        parent_id = uuid4()
        page_start = min(unit.page_start for unit in leaf_units)
        page_end = max(unit.page_end for unit in leaf_units)

        chunks: list[Chunk] = []

        parent_chunk = Chunk(
            id=parent_id,
            document_id=document_id,
            unit_type="document",
            heading_path=[],
            page_start=page_start,
            page_end=page_end,
            text=parent_text,
            parent_id=None,
            chunk_index=chunk_index,
        )
        chunks.append(parent_chunk)
        chunk_index += 1

        # Create leaf chunks
        for unit in leaf_units:
            leaf_chunk = Chunk(
                document_id=document_id,
                unit_type=unit.unit_type,
                heading_path=[],
                page_start=unit.page_start,
                page_end=unit.page_end,
                text=unit.text,
                parent_id=parent_id,
                chunk_index=chunk_index,
            )
            chunks.append(leaf_chunk)
            chunk_index += 1

        return chunks


class _LeafUnit:
    __slots__ = ("text", "unit_type", "page_start", "page_end")

    def __init__(
        self,
        *,
        text: str,
        unit_type: str,
        page_start: int,
        page_end: int,
    ) -> None:
        self.text = text
        self.unit_type = unit_type
        self.page_start = page_start
        self.page_end = page_end


def _split_paragraphs(text: str) -> list[str]:
    """Split text on paragraph boundaries (double newline)."""
    return [p for p in text.split("\n\n") if p.strip()]
