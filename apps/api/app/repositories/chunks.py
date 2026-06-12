from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select, update

from app.db.base import session_factory
from app.db.models.chunk import Chunk as ChunkModel
from app.schemas.chunks import Chunk


def persist_chunks(
    *,
    run_id: UUID,
    document_id: UUID,
    chunks: list[Chunk],
) -> list[ChunkModel]:
    """Persist chunks to the database. Idempotent: deletes existing chunks for the document first.

    Atomic: the delete + all inserts run in a single transaction. If any insert
    fails (e.g. unique violation on ``(document_id, chunk_index)``), the
    transaction rolls back and the prior chunks are preserved.
    """
    parent_chunks = [c for c in chunks if c.parent_id is None]
    child_chunks = [c for c in chunks if c.parent_id is not None]

    # The single-parent mapping below only works for loose documents that
    # produce exactly one parent. Book-profile chunking (multi-parent) will
    # need a different mapping strategy when it lands.
    if child_chunks and len(parent_chunks) != 1:
        raise RuntimeError(
            f"persist_chunks currently supports single-parent documents only "
            f"(got {len(parent_chunks)} parents and {len(child_chunks)} children). "
            f"Multi-parent documents require updating the parent_id resolution logic."
        )

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Chunk persistence is not configured: session_factory has no database bind."
            )

        try:
            # Delete existing chunks for this document (idempotent re-chunking).
            session.execute(
                delete(ChunkModel).where(ChunkModel.document_id == document_id)
            )

            schema_to_db_id: dict[UUID | int, UUID] = {}
            db_rows: list[ChunkModel] = []

            # First pass: stage all parents in the session, then a single flush
            # assigns their UUIDs in one round-trip.
            for chunk in parent_chunks:
                row = ChunkModel(
                    document_id=chunk.document_id,
                    unit_type=chunk.unit_type,
                    heading_path=chunk.heading_path,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    text=chunk.text,
                    context_prefix=chunk.context_prefix,
                    parent_id=None,
                    chunk_index=chunk.chunk_index,
                )
                session.add(row)
                db_rows.append(row)

            if parent_chunks:
                session.flush()
                for parent_schema, parent_row in zip(parent_chunks, db_rows[: len(parent_chunks)]):
                    schema_to_db_id[parent_schema.chunk_index] = parent_row.id

            # Map chunker-generated parent UUIDs to DB-assigned UUIDs.
            if parent_chunks:
                parent_db_id = schema_to_db_id[parent_chunks[0].chunk_index]
                for child in child_chunks:
                    assert child.parent_id is not None
                    schema_to_db_id[child.parent_id] = parent_db_id

            # Second pass: stage children with resolved parent_id.
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
                    context_prefix=chunk.context_prefix,
                    parent_id=resolved_parent_id,
                    chunk_index=chunk.chunk_index,
                )
                session.add(row)
                db_rows.append(row)

            session.commit()
            return db_rows
        except Exception:
            session.rollback()
            raise


def set_chunk_context_prefixes(*, prefixes: dict[UUID, str | None]) -> int:
    """Persist the situating context prefix for each chunk id (ADR-0020).

    Called by the contextualize stage after chunk persistence and before
    embedding. Idempotent and re-runnable: passing ``None`` clears a prefix.
    Returns the number of rows updated.
    """
    if not prefixes:
        return 0
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Chunk persistence is not configured: session_factory has no database bind."
            )
        updated = 0
        for chunk_id, prefix in prefixes.items():
            result = session.execute(
                update(ChunkModel)
                .where(ChunkModel.id == chunk_id)
                .values(context_prefix=prefix)
            )
            updated += result.rowcount or 0
        session.commit()
        return updated


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
