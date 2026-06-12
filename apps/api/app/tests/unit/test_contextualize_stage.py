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
from app.db.models.document import Document
from app.db.models.ingestion import IngestionRun, IngestionStage
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.acl_models import AclGrant, AclAllowedUser
from app.repositories.chunks import get_chunks_as_schemas, persist_chunks
from app.repositories.ingestion import ensure_ingestion_stages, update_stage_status
from app.schemas.chunks import Chunk
from app.services.contextualizers.base import ContextualizeInput
from app.services.contextualizers.stub import StubChunkContextualizer
from app.workflows.stages import run_contextualize_stage


class _ExplodingContextualizer:
    """Fails the test if the stage invokes it (skip-path guard)."""

    def contextualize(self, payload: ContextualizeInput):
        raise AssertionError("contextualizer must not be called on the skip path")


class _PartialContextualizer:
    """Returns a prefix for only the first leaf chunk it sees."""

    def contextualize(self, payload: ContextualizeInput):
        first = payload.leaf_chunks[0]
        return {first.id: f"[partial: {payload.document_title}]"}


@pytest.fixture()
def seeded_db():
    tenant_id = uuid4()
    user_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'contextualize-stage-test.db'}"
        engine = create_engine(database_url)
        config = Config(str(Path("infra/migrations/alembic.ini")))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Tenant", slug="ctx-stage-test"))
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email="ctx@example.com",
                    display_name="Ctx User",
                    roles=["editor"],
                )
            )
            document = Document(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                title="Ctx Test Doc",
                source_type="loose_document",
                source_hash="hash-ctx",
                file_name="ctx.txt",
                object_key="documents/ctx.txt",
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
                source_hash="hash-ctx",
            )
            session.add(run)
            session.commit()
            session.refresh(document)
            session.refresh(run)

            document_id = document.id
            run_id = run.id

        stages = ensure_ingestion_stages(
            run_id=run_id, tenant_id=tenant_id, stage_names=["contextualize"]
        )

        try:
            yield {
                "document_id": document_id,
                "run_id": run_id,
                "stage_id": stages[0].id,
            }
        finally:
            session_factory.configure(bind=None)
            engine.dispose()


def _persist_parent_and_leaves(doc_id, run_id, *, leaf_count: int = 2) -> None:
    parent_id = uuid4()
    chunks = [
        Chunk(
            document_id=doc_id,
            unit_type="document",
            heading_path=[],
            page_start=1,
            page_end=1,
            text="Parent document text.",
            parent_id=None,
            chunk_index=0,
        )
    ]
    chunks.extend(
        Chunk(
            document_id=doc_id,
            unit_type="paragraph",
            heading_path=[],
            page_start=1,
            page_end=1,
            text=f"Leaf {i} text.",
            parent_id=parent_id,
            chunk_index=i + 1,
        )
        for i in range(leaf_count)
    )
    persist_chunks(run_id=run_id, document_id=doc_id, chunks=chunks)


def _stage_row(stage_id) -> IngestionStage:
    with session_factory() as session:
        return session.scalar(select(IngestionStage).where(IngestionStage.id == stage_id))


def test_contextualize_stage_sets_prefixes_and_records_counts(seeded_db):
    doc_id = seeded_db["document_id"]
    run_id = seeded_db["run_id"]
    _persist_parent_and_leaves(doc_id, run_id, leaf_count=2)

    result = run_contextualize_stage(
        run_id=run_id,
        stage_id=seeded_db["stage_id"],
        document_id=doc_id,
        chunks=get_chunks_as_schemas(document_id=doc_id),
        contextualizer=StubChunkContextualizer(),
        document_title="Ctx Test Doc",
    )

    assert result == 2
    stage = _stage_row(seeded_db["stage_id"])
    assert stage.status == "completed"
    assert stage.details["contextualized_count"] == 2
    assert stage.details["rows_updated"] == 2

    schemas = get_chunks_as_schemas(document_id=doc_id)
    leaves = [c for c in schemas if c.parent_id is not None]
    parents = [c for c in schemas if c.parent_id is None]
    assert all(c.context_prefix == "[context: Ctx Test Doc]" for c in leaves)
    assert all(c.search_text == f"[context: Ctx Test Doc]\n{c.text}" for c in leaves)
    # Parents are never augmented — only leaf chunks are embedded/indexed.
    assert all(c.context_prefix is None for c in parents)


def test_contextualize_stage_partial_mapping_counts_only_non_empty(seeded_db):
    doc_id = seeded_db["document_id"]
    run_id = seeded_db["run_id"]
    _persist_parent_and_leaves(doc_id, run_id, leaf_count=2)

    result = run_contextualize_stage(
        run_id=run_id,
        stage_id=seeded_db["stage_id"],
        document_id=doc_id,
        chunks=get_chunks_as_schemas(document_id=doc_id),
        contextualizer=_PartialContextualizer(),
        document_title="Ctx Test Doc",
    )

    # One leaf got a prefix; the other was explicitly set to None (cleared),
    # so both rows are written but only one counts as contextualized.
    assert result == 1
    stage = _stage_row(seeded_db["stage_id"])
    assert stage.details["contextualized_count"] == 1
    assert stage.details["rows_updated"] == 2

    leaves = [
        c for c in get_chunks_as_schemas(document_id=doc_id) if c.parent_id is not None
    ]
    prefixes = sorted((c.context_prefix or "") for c in leaves)
    assert prefixes == ["", "[partial: Ctx Test Doc]"]


def test_contextualize_stage_skips_when_already_completed(seeded_db):
    doc_id = seeded_db["document_id"]
    run_id = seeded_db["run_id"]
    _persist_parent_and_leaves(doc_id, run_id)

    update_stage_status(
        stage_id=seeded_db["stage_id"],
        status="completed",
        details={"contextualized_count": 99},
    )

    result = run_contextualize_stage(
        run_id=run_id,
        stage_id=seeded_db["stage_id"],
        document_id=doc_id,
        chunks=get_chunks_as_schemas(document_id=doc_id),
        contextualizer=_ExplodingContextualizer(),
        document_title="Ctx Test Doc",
    )

    assert result is None
    stage = _stage_row(seeded_db["stage_id"])
    assert stage.details == {"contextualized_count": 99}


def test_contextualize_stage_no_leaf_short_circuit(seeded_db):
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
                text="Parent only.",
                parent_id=None,
                chunk_index=0,
            )
        ],
    )

    result = run_contextualize_stage(
        run_id=run_id,
        stage_id=seeded_db["stage_id"],
        document_id=doc_id,
        chunks=get_chunks_as_schemas(document_id=doc_id),
        contextualizer=_ExplodingContextualizer(),
        document_title="Ctx Test Doc",
    )

    assert result == 0
    stage = _stage_row(seeded_db["stage_id"])
    assert stage.status == "completed"
    assert stage.details == {"contextualized_count": 0}
