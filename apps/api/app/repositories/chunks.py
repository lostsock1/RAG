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

    # Multi-parent safe: each child references its parent by the parent's
    # chunker-assigned ``id``, which this function resolves to the DB-assigned id
    # after flush. Both the loose chunker (one document parent) and the book
    # chunker (one parent per section) follow this convention. A child whose
    # parent carries no id cannot be linked — fail loudly rather than orphan it.
    if child_chunks:
        parents_without_id = [c for c in parent_chunks if c.id is None]
        if parents_without_id:
            raise RuntimeError(
                "persist_chunks requires every parent chunk to carry a chunker-assigned "
                "`id` that its children reference via `parent_id`; "
                f"{len(parents_without_id)} of {len(parent_chunks)} parent(s) had id=None."
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

            schema_to_db_id: dict[UUID, UUID] = {}
            db_rows: list[ChunkModel] = []

            # First pass: stage all parents in the session, then a single flush
            # assigns their UUIDs in one round-trip. Map each parent's
            # chunker-assigned id -> DB id so children (and multiple parents)
            # resolve unambiguously.
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
                    if parent_schema.id is not None:
                        schema_to_db_id[parent_schema.id] = parent_row.id

            # Second pass: stage children with their parent_id resolved to the DB
            # id. A child referencing an unknown parent is a chunker bug — fail
            # loudly rather than persist an orphan or a dangling FK.
            for chunk in child_chunks:
                assert chunk.parent_id is not None
                resolved_parent_id = schema_to_db_id.get(chunk.parent_id)
                if resolved_parent_id is None:
                    raise RuntimeError(
                        f"persist_chunks: child chunk (index {chunk.chunk_index}) references "
                        f"parent_id {chunk.parent_id}, which is not among the document's "
                        f"{len(parent_chunks)} parent chunk(s)."
                    )

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
