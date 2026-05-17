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
