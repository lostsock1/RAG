# Chunking Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `chunk` stage to the ingestion pipeline that splits parsed documents into parent-child chunks, persists them to the `chunks` table, and passes them to the next pipeline stage.

**Architecture:** Structure-aware chunking walks the `ParsedArtifact` pages/tables to produce leaf chunks (paragraphs, tables) and parent chunks (sections). The `Chunker` protocol is profile-routable — `LooseDocumentChunker` for loose documents, `BookChunker` deferred to Phase 5. Chunks are persisted to a new `chunks` DB table matching the domain model in `DOMAIN_MODEL.md`. The `PipelineRunner` gains a new stage between `persist_artifact` and `quality_report`.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2, Alembic, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `apps/api/app/schemas/chunks.py` | `Chunk` Pydantic model, `DocumentProfile` enum |
| `apps/api/app/services/chunkers/base.py` | `Chunker` protocol |
| `apps/api/app/services/chunkers/loose.py` | `LooseDocumentChunker` — structure-aware chunking for loose docs |
| `apps/api/app/services/chunkers/__init__.py` | Re-exports |
| `apps/api/app/db/models/chunk.py` | SQLAlchemy `Chunk` ORM model |
| `apps/api/app/db/models/__init__.py` | Register new model |
| `apps/api/app/repositories/chunks.py` | `persist_chunks`, `get_chunks_for_document` |
| `infra/migrations/versions/20260517_0006_chunks_table.py` | Alembic migration for `chunks` table |
| `apps/api/app/workflows/stages.py` | Add `run_chunk_stage` |
| `apps/api/app/workflows/pipeline_runner.py` | Add `chunk` to `STAGE_NAMES`, wire stage |
| `apps/api/app/tests/unit/test_chunker.py` | Unit tests for chunker |
| `apps/api/app/tests/unit/test_chunks_repository.py` | Unit tests for chunk persistence |
| `apps/api/app/tests/integration/test_ingestion_dispatch.py` | Update to verify chunk stage runs |

---

### Task 1: Chunk schema + Chunker protocol

**Files:**
- Create: `apps/api/app/schemas/chunks.py`
- Create: `apps/api/app/services/chunkers/base.py`
- Create: `apps/api/app/services/chunkers/__init__.py`
- Test: `apps/api/app/tests/unit/test_chunker.py`

- [ ] **Step 1: Write the failing test for Chunk schema**

Create `apps/api/app/tests/unit/test_chunker.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_chunker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.schemas.chunks'`

- [ ] **Step 3: Create the Chunk schema**

Create `apps/api/app/schemas/chunks.py`:

```python
from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentProfile(StrEnum):
    LOOSE = "loose"
    BOOK = "book"


class Chunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    unit_type: str
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    text: str
    parent_id: UUID | None = None
    chunk_index: int
```

- [ ] **Step 4: Create the Chunker protocol**

Create `apps/api/app/services/chunkers/__init__.py`:

```python
from app.services.chunkers.base import Chunker

__all__ = ["Chunker"]
```

Create `apps/api/app/services/chunkers/base.py`:

```python
from __future__ import annotations

from typing import Protocol

from app.schemas.chunks import Chunk, DocumentProfile
from app.schemas.parsed_artifacts import ParsedArtifact


class Chunker(Protocol):
    def chunk(
        self,
        artifact: ParsedArtifact,
        *,
        profile: DocumentProfile,
    ) -> list[Chunk]:
        """Split a parsed artifact into chunks with parent-child relationships.

        Must be deterministic: same input always produces same output.
        """
        ...
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_chunker.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
cd /Users/djesys/RAG && git add apps/api/app/schemas/chunks.py apps/api/app/services/chunkers/ apps/api/app/tests/unit/test_chunker.py && git commit -m "feat: add Chunk schema, DocumentProfile enum, and Chunker protocol"
```

---

### Task 2: LooseDocumentChunker implementation

**Files:**
- Create: `apps/api/app/services/chunkers/loose.py`
- Modify: `apps/api/app/services/chunkers/__init__.py`
- Test: `apps/api/app/tests/unit/test_chunker.py` (extend)

- [ ] **Step 1: Write the failing tests for LooseDocumentChunker**

Append to `apps/api/app/tests/unit/test_chunker.py`:

```python
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
    # Flat doc: one parent wrapping all content, leaves are the actual units
    assert len(parents) >= 1
    assert len(leaves) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_chunker.py -v -k "loose"`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.chunkers.loose'`

- [ ] **Step 3: Implement LooseDocumentChunker**

Create `apps/api/app/services/chunkers/loose.py`:

```python
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
        chunks: list[Chunk] = []
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

        parent_chunk = Chunk(
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
```

Update `apps/api/app/services/chunkers/__init__.py`:

```python
from app.services.chunkers.base import Chunker
from app.services.chunkers.loose import LooseDocumentChunker

__all__ = ["Chunker", "LooseDocumentChunker"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_chunker.py -v`
Expected: All tests pass (4 schema tests + 7 chunker tests = 11)

- [ ] **Step 5: Commit**

```bash
cd /Users/djesys/RAG && git add apps/api/app/services/chunkers/ apps/api/app/tests/unit/test_chunker.py && git commit -m "feat: implement LooseDocumentChunker with parent-child hierarchy"
```

---

### Task 3: Chunk DB model + migration + repository

**Files:**
- Create: `apps/api/app/db/models/chunk.py`
- Modify: `apps/api/app/db/models/__init__.py`
- Create: `infra/migrations/versions/20260517_0006_chunks_table.py`
- Create: `apps/api/app/repositories/chunks.py`
- Test: `apps/api/app/tests/unit/test_chunks_repository.py`

- [ ] **Step 1: Write the failing test for chunk persistence**

Create `apps/api/app/tests/unit/test_chunks_repository.py`:

```python
from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.db.base import session_factory
from app.db.models.chunk import Chunk as ChunkModel
from app.db.models.document import Document
from app.db.models.ingestion import IngestionRun
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.models.acl import AclGrant, AclAllowedUser
from app.repositories.chunks import persist_chunks, get_chunks_for_document
from app.schemas.chunks import Chunk


@pytest.fixture()
def seeded_db():
    tenant_id = uuid4()
    user_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'chunks-test.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Tenant", slug="chunks-test"))
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email="chunks@example.com",
                    display_name="Chunks User",
                    roles=["editor"],
                )
            )
            document = Document(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                title="Chunks Test Doc",
                source_type="loose_document",
                source_hash="hash-chunks",
                file_name="chunks.txt",
                object_key="documents/chunks.txt",
                ingestion_status="uploaded",
            )
            session.add(document)
            session.flush()
            acl_grant = AclGrant(
                document_id=document.id,
                owner_user_id=user_id,
                tenant_id=tenant_id,
                visibility="private",
                sensitivity="internal",
            )
            session.add(acl_grant)
            session.flush()
            session.add(AclAllowedUser(acl_grant_id=acl_grant.id, user_id=user_id))

            run = IngestionRun(
                document_id=document.id,
                tenant_id=tenant_id,
                parser_backend="docling-local",
                source_hash="hash-chunks",
            )
            session.add(run)
            session.commit()
            session.refresh(document)
            session.refresh(run)

            document_id = document.id
            run_id = run.id

        try:
            yield {
                "document_id": document_id,
                "run_id": run_id,
                "tenant_id": tenant_id,
            }
        finally:
            session_factory.configure(bind=None)
            engine.dispose()


def test_persist_chunks_creates_rows(seeded_db):
    doc_id = seeded_db["document_id"]
    run_id = seeded_db["run_id"]

    parent_id = uuid4()
    schema_chunks = [
        Chunk(
            document_id=doc_id,
            unit_type="document",
            heading_path=[],
            page_start=1,
            page_end=2,
            text="Parent chunk text",
            parent_id=None,
            chunk_index=0,
        ),
        Chunk(
            document_id=doc_id,
            unit_type="paragraph",
            heading_path=[],
            page_start=1,
            page_end=1,
            text="Leaf chunk text",
            parent_id=parent_id,
            chunk_index=1,
        ),
    ]

    persist_chunks(run_id=run_id, document_id=doc_id, chunks=schema_chunks)

    result = get_chunks_for_document(document_id=doc_id)
    assert len(result) == 2
    assert result[0].unit_type == "document"
    assert result[1].unit_type == "paragraph"


def test_persist_chunks_idempotent(seeded_db):
    """Persisting the same chunks twice should not duplicate rows."""
    doc_id = seeded_db["document_id"]
    run_id = seeded_db["run_id"]

    schema_chunks = [
        Chunk(
            document_id=doc_id,
            unit_type="paragraph",
            heading_path=[],
            page_start=1,
            page_end=1,
            text="Idempotent chunk",
            parent_id=None,
            chunk_index=0,
        ),
    ]

    persist_chunks(run_id=run_id, document_id=doc_id, chunks=schema_chunks)
    persist_chunks(run_id=run_id, document_id=doc_id, chunks=schema_chunks)

    result = get_chunks_for_document(document_id=doc_id)
    assert len(result) == 1


def test_get_chunks_for_document_empty(seeded_db):
    doc_id = seeded_db["document_id"]
    result = get_chunks_for_document(document_id=doc_id)
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_chunks_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.chunk'`

- [ ] **Step 3: Create the Chunk DB model**

Create `apps/api/app/db/models/chunk.py`:

```python
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, json_type


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_chunks_document_chunk_index",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_type: Mapped[str] = mapped_column(String(length=32), nullable=False)
    heading_path: Mapped[dict] = mapped_column(json_type(), nullable=False, default=list, server_default="[]")
    page_start: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    text: Mapped[str] = mapped_column(Text(), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chunks.id"), nullable=True, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    is_tombstoned: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

Update `apps/api/app/db/models/__init__.py` — add import:

```python
from app.db.models.chunk import Chunk
```

- [ ] **Step 4: Create the Alembic migration**

Create `infra/migrations/versions/20260517_0006_chunks_table.py`:

```python
"""chunks table

Revision ID: 20260517_0006
Revises: 20260517_0005
Create Date: 2026-05-17 00:06:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260517_0006"
down_revision = "20260517_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("unit_type", sa.String(length=32), nullable=False),
        sa.Column("heading_path", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("is_tombstoned", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_chunks_document_id_documents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["chunks.id"], name=op.f("fk_chunks_parent_id_chunks")),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_chunk_index"),
    )
    op.create_index(op.f("ix_chunks_document_id"), "chunks", ["document_id"])
    op.create_index(op.f("ix_chunks_parent_id"), "chunks", ["parent_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_chunks_parent_id"), table_name="chunks")
    op.drop_index(op.f("ix_chunks_document_id"), table_name="chunks")
    op.drop_table("chunks")
```

- [ ] **Step 5: Create the chunks repository**

Create `apps/api/app/repositories/chunks.py`:

```python
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select

from app.db.base import session_factory
from app.db.models.chunk import Chunk as ChunkModel
from app.schemas.chunks import Chunk


def persist_chunks(
    *,
    run_id: UUID,
    document_id: UUID,
    chunks: list[Chunk],
) -> list[ChunkModel]:
    """Persist chunks to the database. Idempotent: deletes existing chunks for the document first."""
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Chunk persistence is not configured: session_factory has no database bind."
            )

        # Delete existing chunks for this document (idempotent re-chunking)
        session.execute(
            delete(ChunkModel).where(ChunkModel.document_id == document_id)
        )

        # Build a mapping from schema parent_id to DB model id
        # Since schema chunks may reference parent_ids that are schema-generated UUIDs,
        # we need to map them to the DB model UUIDs
        id_map: dict[UUID, UUID] = {}

        # First pass: create parent chunks (parent_id is None)
        parent_chunks = [c for c in chunks if c.parent_id is None]
        child_chunks = [c for c in chunks if c.parent_id is not None]

        db_rows: list[ChunkModel] = []

        for chunk in parent_chunks:
            row = ChunkModel(
                document_id=chunk.document_id,
                unit_type=chunk.unit_type,
                heading_path=chunk.heading_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                text=chunk.text,
                parent_id=None,
                chunk_index=chunk.chunk_index,
            )
            session.add(row)
            session.flush()
            id_map[chunk.chunk_index] = row.id  # Use chunk_index as key for parents
            db_rows.append(row)

        # Second pass: create child chunks with resolved parent_id
        for chunk in child_chunks:
            # Find the parent chunk by matching parent_id to a parent's UUID
            # The parent_id in the schema is the UUID we generated for the parent
            # We need to find which parent chunk has that UUID
            parent_row = None
            for parent_chunk in parent_chunks:
                if chunk.parent_id == id_map.get(parent_chunk.chunk_index):
                    parent_row = id_map[parent_chunk.chunk_index]
                    break

            # If we can't resolve by chunk_index mapping, try direct UUID match
            # (the parent_id might already be a DB-assigned UUID from a previous run)
            if parent_row is None:
                parent_row = chunk.parent_id

            row = ChunkModel(
                document_id=chunk.document_id,
                unit_type=chunk.unit_type,
                heading_path=chunk.heading_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                text=chunk.text,
                parent_id=parent_row,
                chunk_index=chunk.chunk_index,
            )
            session.add(row)
            db_rows.append(row)

        session.commit()
        return db_rows


def get_chunks_for_document(*, document_id: UUID) -> list[ChunkModel]:
    """Return all non-tombstoned chunks for a document, ordered by chunk_index."""
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Chunk persistence is not configured: session_factory has no database bind."
            )

        rows = session.scalars(
            select(ChunkModel)
            .where(
                ChunkModel.document_id == document_id,
                ChunkModel.is_tombstoned == False,  # noqa: E712
            )
            .order_by(ChunkModel.chunk_index.asc())
        ).all()
        return list(rows)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_chunks_repository.py -v`
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
cd /Users/djesys/RAG && git add apps/api/app/db/models/chunk.py apps/api/app/db/models/__init__.py infra/migrations/versions/20260517_0006_chunks_table.py apps/api/app/repositories/chunks.py apps/api/app/tests/unit/test_chunks_repository.py && git commit -m "feat: add chunks DB model, migration, and persistence repository"
```

---

### Task 4: Wire chunk stage into PipelineRunner

**Files:**
- Modify: `apps/api/app/workflows/stages.py`
- Modify: `apps/api/app/workflows/pipeline_runner.py`
- Test: `apps/api/app/tests/unit/test_dispatcher.py` (extend)

- [ ] **Step 1: Write the failing test for chunk stage in pipeline**

Append to `apps/api/app/tests/unit/test_dispatcher.py`:

```python
from app.schemas.chunks import DocumentProfile
from app.services.chunkers.loose import LooseDocumentChunker


def test_pipeline_runner_includes_chunk_stage(seeded_env):
    """PipelineRunner STAGE_NAMES must include 'chunk'."""
    from app.workflows.pipeline_runner import STAGE_NAMES
    assert "chunk" in STAGE_NAMES


def test_run_chunk_stage_produces_chunks(seeded_env):
    """run_chunk_stage should produce chunks from a parsed artifact."""
    from app.workflows.stages import run_chunk_stage

    run_id = seeded_env["run_id"]
    document_id = seeded_env["document_id"]

    # First parse to get an artifact
    parse_stage_id = seeded_env["stage_ids"]["parse"]
    test_artifact = _make_test_artifact(document_id)
    parser = DoclingDocumentParser(converter=lambda _req: test_artifact)
    ocr_service = StubOcrService(
        result=OcrResult(
            applied=False,
            engine="none",
            provider="docling-local",
            status="not-applied",
            page_numbers=[],
            notes=[],
        )
    )
    run_parse_stage(
        run_id=run_id,
        stage_id=parse_stage_id,
        document_id=document_id,
        object_key="documents/dispatcher.txt",
        content_type="text/plain",
        profile="local-cpu",
        parser_backend="docling-local",
        parser=parser,
        ocr_service=ocr_service,
    )

    # Now create a chunk stage and run it
    stages = ensure_ingestion_stages(
        run_id=run_id,
        tenant_id=seeded_env["tenant_id"],
        stage_names=["chunk"],
    )
    chunk_stage_id = stages[0].id

    chunks = run_chunk_stage(
        run_id=run_id,
        stage_id=chunk_stage_id,
        document_id=document_id,
        artifact=test_artifact,
        source_type="loose_document",
    )

    assert chunks is not None
    assert len(chunks) > 0
    assert all(c.document_id == document_id for c in chunks)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_dispatcher.py -v -k "chunk"`
Expected: FAIL — `ImportError: cannot import name 'run_chunk_stage'`

- [ ] **Step 3: Implement run_chunk_stage**

Add to `apps/api/app/workflows/stages.py` — add imports at top:

```python
from app.schemas.chunks import Chunk, DocumentProfile
from app.services.chunkers.loose import LooseDocumentChunker
```

Add function at end of `apps/api/app/workflows/stages.py`:

```python
def run_chunk_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    document_id: UUID,
    artifact: ParsedArtifact,
    source_type: str,
) -> list[Chunk] | None:
    """Run the chunk stage. Returns None if stage was already completed (skipped)."""
    if _is_stage_completed(run_id=run_id, stage_name="chunk"):
        logger.info("Stage chunk already completed for run %s, skipping.", run_id)
        return None

    update_stage_status(stage_id=stage_id, status="running")

    profile = DocumentProfile.LOOSE if source_type == "loose_document" else DocumentProfile.BOOK
    chunker = LooseDocumentChunker()
    chunks = chunker.chunk(artifact, profile=profile)

    update_stage_status(
        stage_id=stage_id,
        status="completed",
        details={
            "chunk_count": len(chunks),
            "leaf_count": sum(1 for c in chunks if c.parent_id is not None),
            "parent_count": sum(1 for c in chunks if c.parent_id is None),
            "profile": profile.value,
        },
    )

    return chunks
```

- [ ] **Step 4: Update PipelineRunner STAGE_NAMES and wire chunk stage**

In `apps/api/app/workflows/pipeline_runner.py`, change:

```python
STAGE_NAMES = ["parse", "persist_artifact", "quality_report"]
```

to:

```python
STAGE_NAMES = ["parse", "persist_artifact", "chunk", "quality_report"]
```

Add import:

```python
from app.workflows.stages import run_parse_stage, run_persist_artifact_stage, run_chunk_stage, run_quality_report_stage
from app.repositories.chunks import persist_chunks
```

In the `run` method, after the `persist_artifact` stage block and before the `quality_report` stage block, add:

```python
            # Stage 3: Chunk
            if artifact is not None:
                chunks = run_chunk_stage(
                    run_id=run_id,
                    stage_id=stage_map["chunk"].id,
                    document_id=document_id,
                    artifact=artifact,
                    source_type=doc.source_type if doc else "loose_document",
                )
                if chunks is not None:
                    persist_chunks(
                        run_id=run_id,
                        document_id=document_id,
                        chunks=chunks,
                    )
```

Also fix the `doc` variable — it's currently used after the `with` block closes. Move the `source_type` capture inside the `with` block. Change:

```python
            doc = session.scalar(select(Document).where(Document.id == document_id))
            object_key = doc.object_key if doc else ""
            content_type = "application/octet-stream"
```

to:

```python
            doc = session.scalar(select(Document).where(Document.id == document_id))
            object_key = doc.object_key if doc else ""
            content_type = "application/octet-stream"
            source_type = doc.source_type if doc else "loose_document"
```

And update the chunk stage call to use `source_type`:

```python
                    source_type=source_type,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_dispatcher.py -v -k "chunk"`
Expected: 2 passed

- [ ] **Step 6: Run full dispatcher test suite to verify no regressions**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_dispatcher.py -v`
Expected: All tests pass (existing + 2 new)

- [ ] **Step 7: Commit**

```bash
cd /Users/djesys/RAG && git add apps/api/app/workflows/stages.py apps/api/app/workflows/pipeline_runner.py apps/api/app/tests/unit/test_dispatcher.py && git commit -m "feat: wire chunk stage into PipelineRunner between persist_artifact and quality_report"
```

---

### Task 5: Integration test — full pipeline with chunking

**Files:**
- Modify: `apps/api/app/tests/integration/test_ingestion_dispatch.py`

- [ ] **Step 1: Read the existing integration test to understand the pattern**

Read `apps/api/app/tests/integration/test_ingestion_dispatch.py` to understand the existing test structure and fixture.

- [ ] **Step 2: Write the integration test**

Add a test that verifies the full pipeline (parse → persist → chunk → quality_report) runs end-to-end and produces chunks in the database. Follow the existing fixture pattern from the file.

The test should:
1. Set up a seeded DB with tenant, user, document, ACL, ingestion run.
2. Run `PipelineRunner.run()`.
3. Assert the `chunk` stage completed.
4. Assert chunks exist in the DB for the document.
5. Assert chunk count > 0 and parent-child relationships are correct.

- [ ] **Step 3: Run the integration test**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/integration/test_ingestion_dispatch.py -v`
Expected: All tests pass

- [ ] **Step 4: Run the full test suite**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
cd /Users/djesys/RAG && git add apps/api/app/tests/integration/test_ingestion_dispatch.py && git commit -m "test: add integration test for full pipeline with chunking stage"
```

---

### Task 6: Update project memory

**Files:**
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`
- Modify: `docs/uber-rag/ARCHITECTURE_DECISIONS.md` (promote ADR-0012 to Accepted)

- [ ] **Step 1: Promote ADR-0012 to Accepted**

In `docs/uber-rag/ARCHITECTURE_DECISIONS.md`, change:

```
- [ADR-0012 — Chunking Strategy: Structure-Aware Parent-Child with Profile Routing](adr/0012-chunking-strategy.md) — Proposed 2026-05-17
```

to:

```
- [ADR-0012 — Chunking Strategy: Structure-Aware Parent-Child with Profile Routing](adr/0012-chunking-strategy.md) — Accepted 2026-05-17
```

- [ ] **Step 2: Update PROJECT_STATE.md**

Add to the implementation state section:
- Chunking: `LooseDocumentChunker` implemented with parent-child hierarchy, `Chunk` schema and DB model, `chunks` table migration, chunk persistence repository, and `chunk` stage wired into `PipelineRunner`.

Add to recent changes table.

- [ ] **Step 3: Update TASKS.md**

Mark chunking-related tasks as done:
- `[x] Create chunking interfaces.`
- `[x] Implement loose document profile chunking.`

- [ ] **Step 4: Commit**

```bash
cd /Users/djesys/RAG && git add docs/uber-rag/ && git commit -m "docs: update project memory for chunking stage implementation"
```
