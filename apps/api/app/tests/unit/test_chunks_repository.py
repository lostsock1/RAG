from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.db.base import session_factory
from app.db.models.chunk import Chunk as ChunkModel
from app.db.models.document import Document
from app.db.models.ingestion import IngestionRun
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.acl_models import AclGrant, AclAllowedUser
from app.repositories.chunks import (
    get_chunks_as_schemas,
    get_chunks_for_document,
    persist_chunks,
    set_chunk_context_prefixes,
)
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


def test_persist_chunks_rolls_back_on_child_insert_failure(seeded_db):
    """P1-7: if a child insert fails (e.g. unique violation on
    ``(document_id, chunk_index)``), the entire transaction rolls back and
    the previously-persisted chunks are preserved.
    """
    from sqlalchemy.exc import IntegrityError

    doc_id = seeded_db["document_id"]
    run_id = seeded_db["run_id"]

    # First persist: seed three chunks (one parent, two leaves).
    parent_id = uuid4()
    initial = [
        Chunk(
            document_id=doc_id,
            unit_type="document",
            heading_path=[],
            page_start=1,
            page_end=2,
            text="Original parent",
            parent_id=None,
            chunk_index=0,
        ),
        Chunk(
            document_id=doc_id,
            unit_type="paragraph",
            heading_path=[],
            page_start=1,
            page_end=1,
            text="Original leaf A",
            parent_id=parent_id,
            chunk_index=1,
        ),
        Chunk(
            document_id=doc_id,
            unit_type="paragraph",
            heading_path=[],
            page_start=2,
            page_end=2,
            text="Original leaf B",
            parent_id=parent_id,
            chunk_index=2,
        ),
    ]
    persist_chunks(run_id=run_id, document_id=doc_id, chunks=initial)
    assert len(get_chunks_for_document(document_id=doc_id)) == 3

    # Second persist: payload with two children at the same chunk_index, which
    # violates the uq_chunks_document_chunk_index unique constraint at commit.
    bad_parent_id = uuid4()
    bad_payload = [
        Chunk(
            document_id=doc_id,
            unit_type="document",
            heading_path=[],
            page_start=1,
            page_end=2,
            text="New parent",
            parent_id=None,
            chunk_index=0,
        ),
        Chunk(
            document_id=doc_id,
            unit_type="paragraph",
            heading_path=[],
            page_start=1,
            page_end=1,
            text="New leaf at conflicting index",
            parent_id=bad_parent_id,
            chunk_index=1,
        ),
        Chunk(
            document_id=doc_id,
            unit_type="paragraph",
            heading_path=[],
            page_start=2,
            page_end=2,
            text="Another leaf at the SAME chunk_index",
            parent_id=bad_parent_id,
            chunk_index=1,  # duplicate — triggers IntegrityError
        ),
    ]
    with pytest.raises(IntegrityError):
        persist_chunks(run_id=run_id, document_id=doc_id, chunks=bad_payload)

    # Rollback must have restored the original three rows. If the delete was
    # not rolled back with the failed inserts, we would see 0 rows here.
    survivors = get_chunks_for_document(document_id=doc_id)
    assert len(survivors) == 3
    assert {row.text for row in survivors} == {
        "Original parent",
        "Original leaf A",
        "Original leaf B",
    }


def _seed_two_chunks(doc_id, run_id) -> None:
    parent_id = uuid4()
    persist_chunks(
        run_id=run_id,
        document_id=doc_id,
        chunks=[
            Chunk(
                document_id=doc_id,
                unit_type="document",
                heading_path=[],
                page_start=1,
                page_end=1,
                text="Parent text",
                parent_id=None,
                chunk_index=0,
            ),
            Chunk(
                document_id=doc_id,
                unit_type="paragraph",
                heading_path=[],
                page_start=1,
                page_end=1,
                text="Leaf text",
                parent_id=parent_id,
                chunk_index=1,
            ),
        ],
    )


def test_persist_chunks_round_trips_context_prefix(seeded_db):
    """ADR-0020: a chunk persisted with a context_prefix keeps it through
    the DB row and the schema mapping."""
    doc_id = seeded_db["document_id"]
    run_id = seeded_db["run_id"]

    persist_chunks(
        run_id=run_id,
        document_id=doc_id,
        chunks=[
            Chunk(
                document_id=doc_id,
                unit_type="document",
                heading_path=[],
                page_start=1,
                page_end=1,
                text="Parent text",
                parent_id=None,
                chunk_index=0,
            ),
            Chunk(
                document_id=doc_id,
                unit_type="paragraph",
                heading_path=[],
                page_start=1,
                page_end=1,
                text="Leaf text",
                parent_id=uuid4(),
                chunk_index=1,
                context_prefix="Doc > Section (p. 1)",
            ),
        ],
    )

    leaf_row = next(
        r for r in get_chunks_for_document(document_id=doc_id) if r.parent_id is not None
    )
    assert leaf_row.context_prefix == "Doc > Section (p. 1)"
    leaf_schema = next(
        c for c in get_chunks_as_schemas(document_id=doc_id) if c.parent_id is not None
    )
    assert leaf_schema.context_prefix == "Doc > Section (p. 1)"
    assert leaf_schema.search_text == "Doc > Section (p. 1)\nLeaf text"


def test_set_chunk_context_prefixes_round_trip(seeded_db):
    """ADR-0020: prefixes set after persistence land on the rows and the
    returned rowcount reflects the updates."""
    doc_id = seeded_db["document_id"]
    run_id = seeded_db["run_id"]
    _seed_two_chunks(doc_id, run_id)

    rows = get_chunks_for_document(document_id=doc_id)
    leaf = next(r for r in rows if r.parent_id is not None)

    updated = set_chunk_context_prefixes(prefixes={leaf.id: "Situating context"})
    assert updated == 1

    schemas = get_chunks_as_schemas(document_id=doc_id)
    leaf_schema = next(c for c in schemas if c.parent_id is not None)
    parent_schema = next(c for c in schemas if c.parent_id is None)
    assert leaf_schema.context_prefix == "Situating context"
    assert leaf_schema.search_text == "Situating context\nLeaf text"
    assert parent_schema.context_prefix is None


def test_set_chunk_context_prefixes_none_clears(seeded_db):
    doc_id = seeded_db["document_id"]
    run_id = seeded_db["run_id"]
    _seed_two_chunks(doc_id, run_id)

    leaf = next(
        r for r in get_chunks_for_document(document_id=doc_id) if r.parent_id is not None
    )
    assert set_chunk_context_prefixes(prefixes={leaf.id: "Prefix"}) == 1
    assert set_chunk_context_prefixes(prefixes={leaf.id: None}) == 1

    reloaded = next(
        r for r in get_chunks_for_document(document_id=doc_id) if r.parent_id is not None
    )
    assert reloaded.context_prefix is None


def test_set_chunk_context_prefixes_empty_and_unknown_ids(seeded_db):
    assert set_chunk_context_prefixes(prefixes={}) == 0
    # Unknown chunk ids update zero rows rather than failing.
    assert set_chunk_context_prefixes(prefixes={uuid4(): "Prefix"}) == 0
