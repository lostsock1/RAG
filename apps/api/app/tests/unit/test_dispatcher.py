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
from app.db.models.acl import AclAllowedUser, AclGrant
from app.db.models.document import Document
from app.db.models.ingestion import IngestionRun, IngestionStage
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.repositories.ingestion import (
    create_ingestion_stages,
    get_stages_for_run,
    store_parsed_artifact,
    update_stage_status,
)
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance
from app.services.parsers.docling_backend import DoclingDocumentParser
from app.workflows.dispatcher import InProcessDispatcher
from app.workflows.stages import (
    run_parse_stage,
    run_persist_artifact_stage,
    run_quality_report_stage,
)


@pytest.fixture()
def seeded_env():
    """Set up an in-memory SQLite DB with tenant, user, document, ingestion run, and stages."""
    tenant_id = uuid4()
    user_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'dispatcher-test.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Tenant", slug="tenant-dispatcher-test"))
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email="dispatcher@example.com",
                    display_name="Dispatcher User",
                    roles=["editor"],
                )
            )
            document = Document(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                title="Dispatcher Test Doc",
                source_type="loose_document",
                source_hash="hash-dispatcher",
                file_name="dispatcher.txt",
                file_size_bytes=42,
                object_key="documents/dispatcher.txt",
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
                parser_backend="docling",
                source_hash=document.source_hash,
            )
            session.add(run)
            session.commit()
            session.refresh(run)

            # Capture IDs while session is still active to avoid DetachedInstanceError
            document_id = document.id
            run_id = run.id

        stages = create_ingestion_stages(
            run_id=run_id,
            tenant_id=tenant_id,
            stage_names=["parse", "persist_artifact", "quality_report"],
        )
        stage_ids = {s.stage_name: s.id for s in stages}

        try:
            yield {
                "run_id": run_id,
                "document_id": document_id,
                "stage_ids": stage_ids,
                "tenant_id": tenant_id,
                "user_id": user_id,
            }
        finally:
            session_factory.configure(bind=None)
            engine.dispose()


def _make_test_artifact(document_id) -> ParsedArtifact:
    return ParsedArtifact(
        document_id=document_id,
        pages=[
            ParsedPage(page_number=1, text="Hello world from page 1", blocks=[]),
            ParsedPage(page_number=2, text="Hello world from page 2", blocks=[]),
        ],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 100, 50], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="docling", parser_version="2.x", profile="gpu-local"),
    )


def test_run_parse_stage_calls_parser_and_checkpoints(seeded_env) -> None:
    run_id = seeded_env["run_id"]
    document_id = seeded_env["document_id"]
    parse_stage_id = seeded_env["stage_ids"]["parse"]

    test_artifact = _make_test_artifact(document_id)

    parser = DoclingDocumentParser(converter=lambda _req: test_artifact)

    result = run_parse_stage(
        run_id=run_id,
        stage_id=parse_stage_id,
        document_id=document_id,
        object_key="documents/dispatcher.txt",
        content_type="text/plain",
        profile="gpu-local",
        parser_backend="docling",
        parser=parser,
    )

    assert result is not None
    assert result.document_id == document_id
    assert len(result.pages) == 2

    stages = get_stages_for_run(run_id=run_id)
    parse = next(s for s in stages if s.stage_name == "parse")
    assert parse.status == "completed"
    assert parse.details["page_count"] == 2
    assert parse.details["table_count"] == 1
    assert parse.details["parser_backend"] == "docling"


def test_run_persist_artifact_stage_stores_artifact(seeded_env) -> None:
    run_id = seeded_env["run_id"]
    document_id = seeded_env["document_id"]
    persist_stage_id = seeded_env["stage_ids"]["persist_artifact"]

    artifact = _make_test_artifact(document_id)

    run_persist_artifact_stage(
        run_id=run_id,
        stage_id=persist_stage_id,
        artifact=artifact,
    )

    stages = get_stages_for_run(run_id=run_id)
    persist = next(s for s in stages if s.stage_name == "persist_artifact")
    assert persist.status == "completed"


def test_run_quality_report_stage_checkpoints_report(seeded_env) -> None:
    run_id = seeded_env["run_id"]
    document_id = seeded_env["document_id"]
    quality_stage_id = seeded_env["stage_ids"]["quality_report"]

    artifact = _make_test_artifact(document_id)

    # store_parsed_artifact creates the quality report record in the DB
    store_parsed_artifact(run_id=run_id, artifact=artifact)

    run_quality_report_stage(
        run_id=run_id,
        stage_id=quality_stage_id,
        artifact=artifact,
    )

    stages = get_stages_for_run(run_id=run_id)
    quality = next(s for s in stages if s.stage_name == "quality_report")
    assert quality.status == "completed"
    assert "quality_score" in quality.details
    assert quality.details["quality_score"] == 1.0  # both pages have non-empty text


@pytest.fixture()
def dispatcher_env():
    """Set up an in-memory SQLite DB with tenant, user, document, and ingestion run (no stages).

    The dispatcher creates its own stages, so this fixture intentionally omits
    the ``create_ingestion_stages`` call that ``seeded_env`` includes.
    """
    tenant_id = uuid4()
    user_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'dispatcher-integration.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Tenant", slug="tenant-dispatcher-int"))
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email="dispatcher-int@example.com",
                    display_name="Dispatcher Int User",
                    roles=["editor"],
                )
            )
            document = Document(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                title="Dispatcher Integration Doc",
                source_type="loose_document",
                source_hash="hash-dispatcher-int",
                file_name="dispatcher-int.txt",
                file_size_bytes=42,
                object_key="documents/dispatcher-int.txt",
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
                parser_backend="docling",
                source_hash=document.source_hash,
            )
            session.add(run)
            session.commit()
            session.refresh(run)

            document_id = document.id
            run_id = run.id

        try:
            yield {
                "run_id": run_id,
                "document_id": document_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
            }
        finally:
            session_factory.configure(bind=None)
            engine.dispose()


def test_in_process_dispatcher_runs_all_stages(dispatcher_env) -> None:
    """InProcessDispatcher._execute_pipeline runs parse → persist → quality and marks run completed."""
    run_id = dispatcher_env["run_id"]
    document_id = dispatcher_env["document_id"]

    test_artifact = _make_test_artifact(document_id)
    parser = DoclingDocumentParser(converter=lambda _req: test_artifact)
    dispatcher = InProcessDispatcher(parser=parser)

    dispatcher._execute_pipeline(run_id)

    # Verify run status
    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
    assert run is not None
    assert run.status == "completed"

    # Verify all 3 stages are completed
    stages = get_stages_for_run(run_id=run_id)
    assert len(stages) == 3
    for stage in stages:
        assert stage.status == "completed", f"Stage {stage.stage_name} is {stage.status}, expected completed"


def test_in_process_dispatcher_marks_run_failed_on_stage_error(dispatcher_env) -> None:
    """InProcessDispatcher marks the run as failed when a stage raises an exception."""
    run_id = dispatcher_env["run_id"]

    parser = DoclingDocumentParser(converter=lambda _req: (_ for _ in ()).throw(RuntimeError("Parser exploded")))
    dispatcher = InProcessDispatcher(parser=parser)

    dispatcher._execute_pipeline(run_id)

    # Verify run status
    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
    assert run is not None
    assert run.status == "failed"

    # Verify the parse stage is failed with error details
    stages = get_stages_for_run(run_id=run_id)
    parse_stage = next(s for s in stages if s.stage_name == "parse")
    assert parse_stage.status == "failed"
    assert "error" in parse_stage.details
    assert "Parser exploded" in parse_stage.details["error"]


def test_stage_skips_if_already_completed(seeded_env) -> None:
    run_id = seeded_env["run_id"]
    document_id = seeded_env["document_id"]
    parse_stage_id = seeded_env["stage_ids"]["parse"]

    # Manually mark the parse stage as completed with original details
    update_stage_status(
        stage_id=parse_stage_id,
        status="completed",
        details={"page_count": 99, "table_count": 7, "parser_backend": "docling"},
    )

    test_artifact = _make_test_artifact(document_id)
    parser = DoclingDocumentParser(converter=lambda _req: test_artifact)

    result = run_parse_stage(
        run_id=run_id,
        stage_id=parse_stage_id,
        document_id=document_id,
        object_key="documents/dispatcher.txt",
        content_type="text/plain",
        profile="gpu-local",
        parser_backend="docling",
        parser=parser,
    )

    # Stage was skipped — returns None and original details are preserved
    assert result is None

    stages = get_stages_for_run(run_id=run_id)
    parse = next(s for s in stages if s.stage_name == "parse")
    assert parse.status == "completed"
    assert parse.details["page_count"] == 99
    assert parse.details["table_count"] == 7
