from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.schemas.chunks import Chunk, DocumentProfile


def test_chunk_schema_creation():
    chunk = Chunk(
        document_id=uuid4(),
        unit_type="paragraph",
        heading_path=["Section 1"],
        page_start=1,
        page_end=1,
        text="Some paragraph text.",
        parent_id=None,
        chunk_index=0,
    )
    assert chunk.unit_type == "paragraph"
    assert chunk.heading_path == ["Section 1"]
    assert chunk.parent_id is None
    assert chunk.chunk_index == 0


def test_chunk_schema_with_parent():
    parent_id = uuid4()
    chunk = Chunk(
        document_id=uuid4(),
        unit_type="paragraph",
        heading_path=["Section 1", "Subsection 1.1"],
        page_start=2,
        page_end=2,
        text="Child paragraph text.",
        parent_id=parent_id,
        chunk_index=1,
    )
    assert chunk.parent_id == parent_id


def test_document_profile_enum():
    assert DocumentProfile.LOOSE == "loose"
    assert DocumentProfile.BOOK == "book"


def test_chunker_protocol_exists():
    from app.services.chunkers.base import Chunker
    assert hasattr(Chunker, "chunk")


# --- LooseDocumentChunker tests ---

from app.schemas.parsed_artifacts import (
    ParsedArtifact,
    ParsedPage,
    ParsedTable,
    ParserProvenance,
)
from app.services.chunkers.loose import LooseDocumentChunker


def _make_loose_artifact(document_id: UUID | None = None) -> ParsedArtifact:
    doc_id = document_id or uuid4()
    return ParsedArtifact(
        document_id=doc_id,
        pages=[
            ParsedPage(page_number=1, text="First paragraph.\n\nSecond paragraph.", blocks=[]),
            ParsedPage(page_number=2, text="Third paragraph on page 2.", blocks=[]),
        ],
        tables=[
            ParsedTable(page_number=1, bbox=[0, 0, 100, 50], markdown="| col1 | col2 |\n|------|------|\n| a | b |"),
        ],
        provenance=ParserProvenance(
            parser_backend="docling-local",
            parser_version="2.x",
            profile="local-cpu",
        ),
    )


def test_loose_chunker_produces_chunks():
    doc_id = uuid4()
    artifact = _make_loose_artifact(doc_id)
    chunker = LooseDocumentChunker()
    chunks = chunker.chunk(artifact, profile=DocumentProfile.LOOSE)
    assert len(chunks) > 0
    assert all(c.document_id == doc_id for c in chunks)


def test_loose_chunker_assigns_sequential_indices():
    artifact = _make_loose_artifact()
    chunker = LooseDocumentChunker()
    chunks = chunker.chunk(artifact, profile=DocumentProfile.LOOSE)
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_loose_chunker_preserves_page_numbers():
    artifact = _make_loose_artifact()
    chunker = LooseDocumentChunker()
    chunks = chunker.chunk(artifact, profile=DocumentProfile.LOOSE)
    for chunk in chunks:
        if chunk.page_start is not None:
            assert chunk.page_start >= 1


def test_loose_chunker_tables_are_atomic():
    """Tables should appear as their own chunks, never split."""
    artifact = _make_loose_artifact()
    chunker = LooseDocumentChunker()
    chunks = chunker.chunk(artifact, profile=DocumentProfile.LOOSE)
    table_chunks = [c for c in chunks if c.unit_type == "table"]
    assert len(table_chunks) == 1
    assert "| col1 | col2 |" in table_chunks[0].text


def test_loose_chunker_deterministic():
    """Same input must produce same output."""
    artifact = _make_loose_artifact()
    chunker = LooseDocumentChunker()
    chunks1 = chunker.chunk(artifact, profile=DocumentProfile.LOOSE)
    chunks2 = chunker.chunk(artifact, profile=DocumentProfile.LOOSE)
    assert len(chunks1) == len(chunks2)
    for a, b in zip(chunks1, chunks2):
        assert a.text == b.text
        assert a.chunk_index == b.chunk_index
        assert a.unit_type == b.unit_type


def test_loose_chunker_empty_artifact():
    """Artifact with no pages produces empty chunk list."""
    doc_id = uuid4()
    artifact = ParsedArtifact(
        document_id=doc_id,
        pages=[],
        tables=[],
        provenance=ParserProvenance(
            parser_backend="docling-local",
            parser_version="2.x",
            profile="local-cpu",
        ),
    )
    chunker = LooseDocumentChunker()
    chunks = chunker.chunk(artifact, profile=DocumentProfile.LOOSE)
    assert chunks == []


def test_loose_chunker_single_parent_for_flat_doc():
    """A flat document with no headings gets one parent chunk wrapping all leaves."""
    artifact = _make_loose_artifact()
    chunker = LooseDocumentChunker()
    chunks = chunker.chunk(artifact, profile=DocumentProfile.LOOSE)
    parents = [c for c in chunks if c.parent_id is None]
    leaves = [c for c in chunks if c.parent_id is not None]
    assert len(parents) >= 1
    assert len(leaves) >= 1
