from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.db.base import session_factory
from app.repositories.search_sources import get_parent_chunks_by_child_ids, get_source_slice_by_chunk_id


def test_get_parent_chunks_by_child_ids_returns_parent_payloads() -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'search-sources.db'}"
        engine = create_engine(database_url)

        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    unit_type TEXT NOT NULL,
                    heading_path TEXT NOT NULL,
                    page_start INTEGER NULL,
                    page_end INTEGER NULL,
                    text TEXT NOT NULL,
                    parent_id TEXT NULL,
                    chunk_index INTEGER NOT NULL,
                    is_tombstoned BOOLEAN NOT NULL DEFAULT 0,
                    created_at TEXT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO chunks (id, document_id, unit_type, heading_path, page_start, page_end, text, parent_id, chunk_index, is_tombstoned)
                VALUES
                    ('parent-1', 'doc-1', 'section', '["Root"]', 1, 2, 'parent text', NULL, 0, 0),
                    ('child-1', 'doc-1', 'paragraph', '["Root", "Leaf"]', 2, 2, 'child text', 'parent-1', 1, 0)
                """
            )

        session_factory.configure(bind=engine)
        try:
            results = get_parent_chunks_by_child_ids(child_chunk_ids=["child-1"])
        finally:
            session_factory.configure(bind=None)
            engine.dispose()

    assert results == {
        "child-1": {
            "chunk_id": "parent-1",
            "document_id": "doc-1",
            "text": "parent text",
            "heading_path": ["Root"],
            "page_start": 1,
            "page_end": 2,
        }
    }



def test_get_parent_chunks_by_child_ids_matches_hyphenated_ids_against_hex_storage() -> None:
    """SQLAlchemy's Uuid type stores raw hex (no hyphens) on SQLite while
    retrieval hits carry canonical hyphenated UUIDs — the lookup must
    normalize (like get_source_slice_by_chunk_id does) and key the result by
    the caller's id form, or parent expansion silently no-ops."""
    child_hex = "aaaaaaaabbbbccccddddeeeeeeeeeeee"
    parent_hex = "11111111222233334444555555555555"
    child_hyphenated = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'search-sources-hex.db'}"
        engine = create_engine(database_url)

        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    unit_type TEXT NOT NULL,
                    heading_path TEXT NOT NULL,
                    page_start INTEGER NULL,
                    page_end INTEGER NULL,
                    text TEXT NOT NULL,
                    parent_id TEXT NULL,
                    chunk_index INTEGER NOT NULL,
                    is_tombstoned BOOLEAN NOT NULL DEFAULT 0,
                    created_at TEXT NULL
                )
                """
            )
            connection.exec_driver_sql(
                f"""
                INSERT INTO chunks (id, document_id, unit_type, heading_path, page_start, page_end, text, parent_id, chunk_index, is_tombstoned)
                VALUES
                    ('{parent_hex}', 'doc-1', 'document', '[]', 1, 2, 'parent text', NULL, 0, 0),
                    ('{child_hex}', 'doc-1', 'paragraph', '[]', 2, 2, 'child text', '{parent_hex}', 1, 0)
                """
            )

        session_factory.configure(bind=engine)
        try:
            results = get_parent_chunks_by_child_ids(child_chunk_ids=[child_hyphenated])
        finally:
            session_factory.configure(bind=None)
            engine.dispose()

    assert child_hyphenated in results
    assert results[child_hyphenated]["chunk_id"] == "11111111-2222-3333-4444-555555555555"
    assert results[child_hyphenated]["text"] == "parent text"


def test_get_source_slice_by_chunk_id_returns_none_for_chunk_outside_acl_filter() -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'search-sources-acl.db'}"
        engine = create_engine(database_url)

        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE documents (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    object_key TEXT NOT NULL,
                    ingestion_status TEXT NOT NULL,
                    is_tombstoned BOOLEAN NOT NULL DEFAULT 0,
                    created_at TEXT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE acl_grants (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    expires_at TEXT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE acl_allowed_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    acl_grant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE acl_allowed_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    acl_grant_id TEXT NOT NULL,
                    group_id TEXT NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    unit_type TEXT NOT NULL,
                    heading_path TEXT NOT NULL,
                    page_start INTEGER NULL,
                    page_end INTEGER NULL,
                    text TEXT NOT NULL,
                    parent_id TEXT NULL,
                    chunk_index INTEGER NOT NULL,
                    is_tombstoned BOOLEAN NOT NULL DEFAULT 0,
                    created_at TEXT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO documents (id, tenant_id, owner_user_id, title, source_type, source_hash, file_name, file_size_bytes, object_key, ingestion_status, is_tombstoned)
                VALUES
                    ('11111111111111111111111111111111', '33333333333333333333333333333333', '44444444444444444444444444444444', 'Visible', 'loose_document', 'hash-visible', 'visible.txt', 1, 'documents/visible.txt', 'completed', 0),
                    ('22222222222222222222222222222222', '33333333333333333333333333333333', '55555555555555555555555555555555', 'Hidden', 'loose_document', 'hash-hidden', 'hidden.txt', 1, 'documents/hidden.txt', 'completed', 0)
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO acl_grants (id, document_id, tenant_id, owner_user_id, visibility, sensitivity, expires_at)
                VALUES
                    ('acl-visible', '11111111111111111111111111111111', '33333333333333333333333333333333', '44444444444444444444444444444444', 'group', 'internal', NULL),
                    ('acl-hidden', '22222222222222222222222222222222', '33333333333333333333333333333333', '55555555555555555555555555555555', 'group', 'internal', NULL)
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO acl_allowed_groups (acl_grant_id, group_id)
                VALUES
                    ('acl-visible', '77777777777777777777777777777777'),
                    ('acl-hidden', '88888888888888888888888888888888')
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO chunks (id, document_id, unit_type, heading_path, page_start, page_end, text, parent_id, chunk_index, is_tombstoned)
                VALUES
                    ('visible-chunk', '11111111111111111111111111111111', 'paragraph', '["Root", "Visible"]', 1, 1, 'visible text', NULL, 0, 0),
                    ('hidden-chunk', '22222222222222222222222222222222', 'paragraph', '["Secret"]', 4, 4, 'hidden text', NULL, 0, 0)
                """
            )

        session_factory.configure(bind=engine)
        try:
            visible_result = get_source_slice_by_chunk_id(
                chunk_id='visible-chunk',
                tenant_id='33333333333333333333333333333333',
                user_id='66666666666666666666666666666666',
                group_ids=['77777777777777777777777777777777'],
                context_window=1,
            )
            hidden_result = get_source_slice_by_chunk_id(
                chunk_id='hidden-chunk',
                tenant_id='33333333333333333333333333333333',
                user_id='66666666666666666666666666666666',
                group_ids=['77777777777777777777777777777777'],
                context_window=1,
            )
        finally:
            session_factory.configure(bind=None)
            engine.dispose()

    assert visible_result is not None
    assert visible_result['document_id'] == '11111111-1111-1111-1111-111111111111'
    assert hidden_result is None
