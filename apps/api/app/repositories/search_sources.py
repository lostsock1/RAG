from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import MetaData, Table, alias, select

from app.db.acl_models import AclGrant
from app.db.base import session_factory
from app.db.models.document import Document
from app.repositories.documents import resolve_group_ids_for_context
from app.services.acl_service import build_document_acl_filter


def _chunks_table(bind: object) -> Table:
    return Table("chunks", MetaData(), autoload_with=bind)


def _normalize_heading_path(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return []


def _normalize_identifier(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    try:
        return str(UUID(text))
    except ValueError:
        return text


def _to_uuid_hex(value: str) -> str:
    """Normalize a UUID string to its raw hex form (no hyphens, no braces).

    This matches the storage format SQLAlchemy's UUID type uses in SQLite.
    If the value is not a valid UUID, returns it unchanged.
    """
    try:
        return UUID(value).hex
    except ValueError:
        return value


def get_parent_chunks_by_child_ids(*, child_chunk_ids: list[str]) -> dict[str, dict[str, object]]:
    if not child_chunk_ids:
        return {}

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Search source lookup is not configured: session_factory has no database bind."
            )

        chunks = _chunks_table(session.bind)
        child = alias(chunks, name="child")
        parent = alias(chunks, name="parent")
        rows = session.execute(
            select(
                child.c.id.label("child_id"),
                parent.c.id.label("parent_id"),
                parent.c.document_id.label("document_id"),
                parent.c.text.label("text"),
                parent.c.heading_path.label("heading_path"),
                parent.c.page_start.label("page_start"),
                parent.c.page_end.label("page_end"),
            )
            .select_from(child.join(parent, parent.c.id == child.c.parent_id))
            .where(
                child.c.id.in_(child_chunk_ids),
                child.c.is_tombstoned.is_(False),
                parent.c.is_tombstoned.is_(False),
            )
        )

        return {
            str(row.child_id): {
                "chunk_id": _normalize_identifier(row.parent_id),
                "document_id": _normalize_identifier(row.document_id),
                "text": row.text,
                "heading_path": _normalize_heading_path(row.heading_path),
                "page_start": row.page_start,
                "page_end": row.page_end,
            }
            for row in rows
        }


def get_source_slice_by_chunk_id(
    *,
    chunk_id: str,
    tenant_id: str,
    user_id: str,
    group_ids: list[str],
    context_window: int = 1,
) -> dict[str, object] | None:
    # Normalize the lookup key to raw hex so it matches the SQLAlchemy UUID
    # storage format in SQLite (no hyphens).  For non-UUID identifiers the
    # value is kept as-is.
    lookup_chunk_id = _to_uuid_hex(chunk_id)

    # Normalize for the is_focus comparison — both sides go through
    # _normalize_identifier so equivalent UUID strings compare equal
    # regardless of hyphenation.
    normalized_focus_id = _normalize_identifier(chunk_id)

    tenant_uuid = UUID(tenant_id)
    user_uuid = UUID(user_id)

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Search source lookup is not configured: session_factory has no database bind."
            )

        resolved_group_ids = resolve_group_ids_for_context(
            session=session,
            tenant_id=tenant_uuid,
            group_ids=group_ids,
        )
        chunks = _chunks_table(session.bind)
        acl_filter = build_document_acl_filter(
            tenant_id=tenant_uuid,
            user_id=user_uuid,
            group_ids=resolved_group_ids,
        )
        focus = session.execute(
            select(
                chunks.c.id,
                chunks.c.document_id,
                Document.title.label("document_title"),
                Document.source_type.label("source_type"),
                chunks.c.parent_id,
                chunks.c.chunk_index,
                chunks.c.text,
                chunks.c.heading_path,
                chunks.c.page_start,
                chunks.c.page_end,
            )
            .select_from(chunks.join(Document, Document.id == chunks.c.document_id).join(AclGrant, AclGrant.document_id == Document.id))
            .where(
                chunks.c.id == lookup_chunk_id,
                chunks.c.is_tombstoned.is_(False),
                acl_filter,
            )
        ).mappings().first()
        if focus is None:
            return None

        if focus["parent_id"] is None or context_window < 1:
            rows = [focus]
        else:
            rows = session.execute(
                select(
                    chunks.c.id,
                    chunks.c.document_id,
                    Document.title.label("document_title"),
                    Document.source_type.label("source_type"),
                    chunks.c.parent_id,
                    chunks.c.chunk_index,
                    chunks.c.text,
                    chunks.c.heading_path,
                    chunks.c.page_start,
                    chunks.c.page_end,
                )
                .select_from(chunks.join(Document, Document.id == chunks.c.document_id).join(AclGrant, AclGrant.document_id == Document.id))
                .where(
                    chunks.c.document_id == focus["document_id"],
                    chunks.c.parent_id == focus["parent_id"],
                    chunks.c.is_tombstoned.is_(False),
                    chunks.c.chunk_index >= max(int(focus["chunk_index"]) - context_window, 0),
                    chunks.c.chunk_index <= int(focus["chunk_index"]) + context_window,
                    acl_filter,
                )
                .order_by(chunks.c.chunk_index.asc())
            ).mappings().all()

        return {
            "chunk_id": _normalize_identifier(focus["id"]),
            "document_id": _normalize_identifier(focus["document_id"]),
            "parent_chunk_id": _normalize_identifier(focus["parent_id"]),
            "document_title": focus["document_title"],
            "source_type": focus["source_type"],
            "items": [
                {
                    "chunk_id": _normalize_identifier(row["id"]),
                    "text": row["text"],
                    "page_start": row["page_start"],
                    "page_end": row["page_end"],
                    "heading_path": _normalize_heading_path(row["heading_path"]),
                    "is_focus": _normalize_identifier(row["id"]) == normalized_focus_id,
                }
                for row in rows
            ],
        }
