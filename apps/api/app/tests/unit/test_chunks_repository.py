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
