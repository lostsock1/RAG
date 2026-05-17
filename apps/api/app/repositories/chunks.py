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

        # Separate parents and children
        parent_chunks = [c for c in chunks if c.parent_id is None]
        child_chunks = [c for c in chunks if c.parent_id is not None]

        # Map schema parent UUID -> DB row UUID for child resolution
        schema_to_db_id: dict[UUID | int, UUID] = {}
        db_rows: list[ChunkModel] = []

        # First pass: create parent chunks
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
            # Map the parent's chunk_index as a synthetic key (parents have parent_id=None)
            # Children reference the parent by the UUID the chunker assigned to the parent's
            # chunk_index position. Since parents don't carry their own UUID in the schema,
            # we use chunk_index as the lookup key for single-parent documents.
            schema_to_db_id[chunk.chunk_index] = row.id
            db_rows.append(row)

        # For single-parent documents (loose docs), all children reference the same parent.
        # Build a reverse map: chunker-generated parent_id -> DB UUID.
        # The chunker sets child.parent_id to the UUID it generated for the parent.
        # We need to map that UUID to the DB-assigned UUID.
        if len(parent_chunks) == 1:
            # All children reference the same parent — use any child's parent_id as the key
            parent_db_id = schema_to_db_id[parent_chunks[0].chunk_index]
            for child in child_chunks:
                assert child.parent_id is not None
                schema_to_db_id[child.parent_id] = parent_db_id

        # Second pass: create child chunks with resolved parent_id
        for chunk in child_chunks:
            assert chunk.parent_id is not None
            resolved_parent_id = schema_to_db_id.get(chunk.parent_id, chunk.parent_id)

            row = ChunkModel(
                document_id=chunk.document_id,
                unit_type=chunk.unit_type,
                heading_path=chunk.heading_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                text=chunk.text,
                parent_id=resolved_parent_id,
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


def get_chunks_as_schemas(*, document_id: UUID) -> list[Chunk]:
    """Return chunks for a document as Pydantic schemas (for pipeline stages)."""
    rows = get_chunks_for_document(document_id=document_id)
    return [row.to_schema() for row in rows]
