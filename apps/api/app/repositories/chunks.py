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

        # Map schema chunk_index -> DB row UUID for parent resolution
        id_map: dict[int, UUID] = {}
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
            id_map[chunk.chunk_index] = row.id
            db_rows.append(row)

        # Second pass: create child chunks with resolved parent_id
        for chunk in child_chunks:
            # Resolve parent_id: find which parent chunk has the matching UUID
            resolved_parent_id: UUID | None = None
            for parent_chunk in parent_chunks:
                if chunk.parent_id == id_map.get(parent_chunk.chunk_index):
                    resolved_parent_id = id_map[parent_chunk.chunk_index]
                    break

            if resolved_parent_id is None:
                # Fallback: the parent_id might already be a DB-assigned UUID
                resolved_parent_id = chunk.parent_id

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
