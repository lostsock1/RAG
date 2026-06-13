from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy import insert

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.db.base import session_factory
from app.db.acl_models import AclAllowedGroup, AclAllowedUser, AclGrant
from app.db.models.document import Document
from app.db.models.ingestion import IngestionRun, IngestionStage, ParsedArtifact as ParsedArtifactRecord
from app.db.models.group import Group
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.repositories.ingestion import (
    create_ingestion_stages,
    ensure_ingestion_stages,
    get_stages_for_run,
    store_parsed_artifact,
    update_run_status,
    update_stage_status,
)
from app.schemas.parsed_artifacts import OcrProvenance, ParsedArtifact, ParsedBlock, ParsedPage, ParsedTable, ParserProvenance
from app.services.ocr import OcrResult, StubOcrService
from app.services.parsers.docling_backend import DoclingDocumentParser
from app.services.parsers.remote_backend import RemoteDocumentParser
from app.services.storage import MaterializedObject, StorageAdapter
from app.repositories.documents import get_document_index_acl_metadata
from app.workflows.dispatcher import InProcessDispatcher
from app.workflows.pipeline_runner import PipelineRunner
from app.workflows.stages import (
    _resolve_parser,
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
                parser_backend="docling-local",
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
        provenance=ParserProvenance(parser_backend="docling-local", parser_version="2.x", profile="local-gpu"),
    )


def test_run_parse_stage_calls_parser_and_checkpoints(seeded_env) -> None:
    run_id = seeded_env["run_id"]
    document_id = seeded_env["document_id"]
    parse_stage_id = seeded_env["stage_ids"]["parse"]

    test_artifact = _make_test_artifact(document_id)

    parser = DoclingDocumentParser(converter=lambda _req: test_artifact)
    ocr_service = StubOcrService(
        result=OcrResult(
            applied=True,
            engine="tesseract",
            provider="docling-local",
            status="applied",
            page_numbers=[2],
            notes=["ocr used on scanned page"],
        )
    )

    result = run_parse_stage(
        run_id=run_id,
        stage_id=parse_stage_id,
        document_id=document_id,
        object_key="documents/dispatcher.txt",
        content_type="text/plain",
        profile="local-gpu",
        parser_backend="docling-local",
        parser=parser,
        ocr_service=ocr_service,
    )

    assert result is not None
    assert result.document_id == document_id
    assert len(result.pages) == 2

    stages = get_stages_for_run(run_id=run_id)
    parse = next(s for s in stages if s.stage_name == "parse")
    assert parse.status == "completed"
    assert parse.details["page_count"] == 2
    assert parse.details["table_count"] == 1
    assert parse.details["parser_backend"] == "docling-local"
    assert parse.details["parser_profile"] == "local-gpu"
    assert result.provenance.parser_backend == "docling-local"
    assert parse.details["ocr"]["applied"] is True
    assert parse.details["ocr"]["status"] == "applied"
    assert parse.details["ocr"]["provider"] == "docling-local"
    assert parse.details["ocr"]["page_count"] == 1
    assert result.provenance.ocr is not None
    assert result.provenance.ocr.page_numbers == [2]


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
    assert quality.details["parser_profile"] == "local-gpu"
    assert quality.details["counts"]["table_count"] == 1


def test_run_parse_stage_marks_default_ocr_provenance_unverified(seeded_env) -> None:
    run_id = seeded_env["run_id"]
    document_id = seeded_env["document_id"]
    parse_stage_id = seeded_env["stage_ids"]["parse"]

    parser = DoclingDocumentParser(converter=lambda _req: _make_test_artifact(document_id))

    result = run_parse_stage(
        run_id=run_id,
        stage_id=parse_stage_id,
        document_id=document_id,
        object_key="documents/dispatcher.txt",
        content_type="text/plain",
        profile="local-cpu",
        parser_backend="docling-local",
        parser=parser,
    )

    assert result is not None
    assert result.provenance.ocr is not None
    assert result.provenance.ocr.status == "unverified"
    assert result.provenance.ocr.applied is None
    assert result.provenance.ocr.provider == "docling-local"

    parse = next(s for s in get_stages_for_run(run_id=run_id) if s.stage_name == "parse")
    assert parse.details["ocr"]["status"] == "unverified"
    assert parse.details["ocr"]["applied"] is None


def test_run_parse_stage_uses_remote_truthful_default_ocr_provenance(seeded_env) -> None:
    run_id = seeded_env["run_id"]
    document_id = seeded_env["document_id"]
    parse_stage_id = seeded_env["stage_ids"]["parse"]

    remote_artifact = ParsedArtifact(
        document_id=document_id,
        pages=[ParsedPage(page_number=1, text="remote page", blocks=[])],
        tables=[],
        provenance=ParserProvenance(
            parser_backend="remote-api",
            parser_version="1.0",
            profile="remote-api",
        ),
    )
    parser = RemoteDocumentParser(invoke_remote_parser=lambda _req: remote_artifact)

    result = run_parse_stage(
        run_id=run_id,
        stage_id=parse_stage_id,
        document_id=document_id,
        object_key="documents/remote.txt",
        content_type="text/plain",
        profile="remote-api",
        parser_backend="remote-api",
        parser=parser,
    )

    assert result is not None
    assert result.provenance.ocr is not None
    assert result.provenance.ocr.status == "unverified"
    assert result.provenance.ocr.provider == "remote-api"
    assert result.provenance.ocr.engine == "remote-service"

    parse = next(s for s in get_stages_for_run(run_id=run_id) if s.stage_name == "parse")
    assert parse.details["ocr"]["provider"] == "remote-api"
    assert parse.details["ocr"]["engine"] == "remote-service"


def test_run_parse_stage_preserves_parser_supplied_ocr_provenance(seeded_env) -> None:
    run_id = seeded_env["run_id"]
    document_id = seeded_env["document_id"]
    parse_stage_id = seeded_env["stage_ids"]["parse"]

    parser_artifact = ParsedArtifact(
        document_id=document_id,
        pages=[ParsedPage(page_number=1, text="page", blocks=[])],
        tables=[],
        provenance=ParserProvenance(
            parser_backend="docling-local",
            parser_version="2.x",
            profile="local-cpu",
            ocr=OcrProvenance(
                status="applied",
                applied=True,
                engine="tesseract",
                provider="docling-local",
                page_numbers=[1],
                notes=["parser detected OCR"],
            ),
        ),
    )
    parser = DoclingDocumentParser(converter=lambda _req: parser_artifact)
    ocr_service = StubOcrService(
        result=OcrResult(
            status="unverified",
            applied=None,
            engine="remote-service",
            provider="remote-api",
            notes=["fallback should not replace parser provenance"],
        )
    )

    result = run_parse_stage(
        run_id=run_id,
        stage_id=parse_stage_id,
        document_id=document_id,
        object_key="documents/dispatcher.txt",
        content_type="text/plain",
        profile="local-cpu",
        parser_backend="docling-local",
        parser=parser,
        ocr_service=ocr_service,
    )

    assert result is not None
    assert result.provenance.ocr is not None
    assert result.provenance.ocr.status == "applied"
    assert result.provenance.ocr.provider == "docling-local"
    assert result.provenance.ocr.notes == ["parser detected OCR"]

    parse = next(s for s in get_stages_for_run(run_id=run_id) if s.stage_name == "parse")
    assert parse.details["ocr"]["status"] == "applied"
    assert parse.details["ocr"]["provider"] == "docling-local"


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
                parser_backend="docling-local",
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
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        ocr_service=StubOcrService(
            result=OcrResult(
                applied=True,
                engine="tesseract",
                provider="docling-local",
                status="applied",
                page_numbers=[1],
                notes=["ocr used for first page"],
            )
        ),
    )

    dispatcher._execute_pipeline(run_id)

    # Verify run status
    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
    assert run is not None
    assert run.status == "completed"

    # Verify all 4 stages are completed
    stages = get_stages_for_run(run_id=run_id)
    assert len(stages) == 7
    for stage in stages:
        assert stage.status == "completed", f"Stage {stage.stage_name} is {stage.status}, expected completed"

    parse_stage = next(stage for stage in stages if stage.stage_name == "parse")
    assert parse_stage.details["parser_backend"] == "docling-local"
    assert parse_stage.details["ocr"]["engine"] == "tesseract"

    with session_factory() as session:
        artifact_record = session.scalar(select(ParsedArtifactRecord).where(ParsedArtifactRecord.run_id == run_id))

    assert artifact_record is not None
    assert artifact_record.artifact_json["provenance"]["profile"] == "local-cpu"
    assert artifact_record.artifact_json["provenance"]["ocr"]["page_numbers"] == [1]


def test_in_process_dispatcher_marks_run_failed_on_stage_error(dispatcher_env) -> None:
    """InProcessDispatcher marks the run as failed when a stage raises an exception."""
    run_id = dispatcher_env["run_id"]

    parser = DoclingDocumentParser(converter=lambda _req: (_ for _ in ()).throw(RuntimeError("Parser exploded")))
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
    )

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


def test_resolve_parser_accepts_docling_local_and_rejects_legacy_docling_name() -> None:
    assert isinstance(_resolve_parser("docling-local"), DoclingDocumentParser)

    with pytest.raises(ValueError) as exc_info:
        _resolve_parser("docling")

    assert "docling-local" in str(exc_info.value)


def test_in_process_dispatcher_skips_when_run_cannot_be_claimed(dispatcher_env) -> None:
    run_id = dispatcher_env["run_id"]

    update_run_status(run_id=run_id, status="running")

    parser = DoclingDocumentParser(converter=lambda _req: (_ for _ in ()).throw(AssertionError("parser should not run")))
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
    )

    dispatcher._execute_pipeline(run_id)

    assert get_stages_for_run(run_id=run_id) == []


def test_in_process_dispatcher_reruns_parse_when_checkpoint_missing(dispatcher_env) -> None:
    run_id = dispatcher_env["run_id"]
    document_id = dispatcher_env["document_id"]
    tenant_id = dispatcher_env["tenant_id"]

    stages = ensure_ingestion_stages(
        run_id=run_id,
        tenant_id=tenant_id,
        stage_names=["parse", "persist_artifact", "quality_report"],
    )
    update_stage_status(stage_id=stages[0].id, status="completed", details={"page_count": 1})
    update_stage_status(stage_id=stages[1].id, status="failed", details={"error": "persist missing"})
    update_stage_status(stage_id=stages[2].id, status="queued")
    update_run_status(run_id=run_id, status="queued")

    test_artifact = _make_test_artifact(document_id)
    parser = DoclingDocumentParser(converter=lambda _req: test_artifact)
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
    )

    dispatcher._execute_pipeline(run_id)

    with session_factory() as session:
        artifact_record = session.scalar(select(ParsedArtifactRecord).where(ParsedArtifactRecord.run_id == run_id))
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))

    assert artifact_record is not None
    assert run is not None
    assert run.status == "completed"

    refreshed_stages = get_stages_for_run(run_id=run_id)
    parse_stage = next(stage for stage in refreshed_stages if stage.stage_name == "parse")
    assert parse_stage.status == "completed"
    assert parse_stage.details["retry_reset_reason"] == "artifact_missing_for_completed_parse"


def test_in_process_dispatcher_reloads_legacy_artifact_payload_when_parse_is_skipped(dispatcher_env) -> None:
    run_id = dispatcher_env["run_id"]
    document_id = dispatcher_env["document_id"]
    tenant_id = dispatcher_env["tenant_id"]

    stages = ensure_ingestion_stages(
        run_id=run_id,
        tenant_id=tenant_id,
        stage_names=["parse", "persist_artifact", "quality_report"],
    )
    update_stage_status(stage_id=stages[0].id, status="completed", details={"page_count": 1, "parser_backend": "docling-local"})
    update_stage_status(stage_id=stages[1].id, status="queued")
    update_stage_status(stage_id=stages[2].id, status="queued")
    update_run_status(run_id=run_id, status="queued")

    legacy_payload = {
        "document_id": str(document_id),
        "pages": [{"page_number": 1, "text": "legacy page", "blocks": []}],
        "tables": [],
        "provenance": {
            "parser_backend": "docling",
            "parser_version": "2.x",
            "profile": "gpu-local",
            "ocr": {
                "status": "applied",
                "applied": True,
                "engine": "tesseract",
                "provider": "docling-local",
                "page_numbers": [1],
                "notes": ["legacy artifact"],
            },
        },
    }

    with session_factory() as session:
        session.execute(
            insert(ParsedArtifactRecord).values(
                run_id=run_id,
                tenant_id=tenant_id,
                artifact_type="structured",
                artifact_json=legacy_payload,
                artifact_hash="legacy-hash",
            )
        )
        session.commit()

    parser = DoclingDocumentParser(converter=lambda _req: (_ for _ in ()).throw(AssertionError("parse should stay skipped")))
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
    )

    dispatcher._execute_pipeline(run_id)

    with session_factory() as session:
        artifact_record = session.scalar(select(ParsedArtifactRecord).where(ParsedArtifactRecord.run_id == run_id))
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))

    assert artifact_record is not None
    assert artifact_record.artifact_json["pages"][0]["text"] == "legacy page"
    assert run is not None
    assert run.status == "completed"

    refreshed_stages = get_stages_for_run(run_id=run_id)
    assert next(stage for stage in refreshed_stages if stage.stage_name == "persist_artifact").status == "completed"
    assert next(stage for stage in refreshed_stages if stage.stage_name == "quality_report").status == "completed"


def test_stage_skips_if_already_completed(seeded_env) -> None:
    run_id = seeded_env["run_id"]
    document_id = seeded_env["document_id"]
    parse_stage_id = seeded_env["stage_ids"]["parse"]

    # Manually mark the parse stage as completed with original details
    update_stage_status(
        stage_id=parse_stage_id,
        status="completed",
        details={"page_count": 99, "table_count": 7, "parser_backend": "docling-local"},
        
    )

    test_artifact = _make_test_artifact(document_id)
    parser = DoclingDocumentParser(converter=lambda _req: test_artifact)

    result = run_parse_stage(
        run_id=run_id,
        stage_id=parse_stage_id,
        document_id=document_id,
        object_key="documents/dispatcher.txt",
        content_type="text/plain",
        profile="local-gpu",
        parser_backend="docling-local",
        parser=parser,
    )

    # Stage was skipped — returns None and original details are preserved
    assert result is None

    stages = get_stages_for_run(run_id=run_id)
    parse = next(s for s in stages if s.stage_name == "parse")
    assert parse.status == "completed"
    assert parse.details["page_count"] == 99
    assert parse.details["table_count"] == 7


def test_in_process_dispatcher_materializes_object_and_cleans_up(dispatcher_env, tmp_path: Path) -> None:
    materialized_file = tmp_path / "materialized.txt"
    materialized_file.write_text("hello")
    cleanup_called = {"value": False}

    class FakeStorage(StorageAdapter):
        def materialize_for_read(self, *, object_key: str) -> MaterializedObject:
            def _cleanup() -> None:
                cleanup_called["value"] = True
            return MaterializedObject(local_path=materialized_file, cleanup=_cleanup)

    run_id = dispatcher_env["run_id"]
    document_id = dispatcher_env["document_id"]

    test_artifact = _make_test_artifact(document_id)
    parser = DoclingDocumentParser(converter=lambda _req: test_artifact)
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        storage=FakeStorage(),
    )

    dispatcher._execute_pipeline(run_id)

    assert cleanup_called["value"] is True

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
    assert run is not None
    assert run.status == "completed"


def test_in_process_dispatcher_cleans_up_on_parse_failure(dispatcher_env, tmp_path: Path) -> None:
    materialized_file = tmp_path / "broken.txt"
    materialized_file.write_text("broken")
    cleanup_called = {"value": False}

    class FakeStorage(StorageAdapter):
        def materialize_for_read(self, *, object_key: str) -> MaterializedObject:
            def _cleanup() -> None:
                cleanup_called["value"] = True
            return MaterializedObject(local_path=materialized_file, cleanup=_cleanup)

    run_id = dispatcher_env["run_id"]

    parser = DoclingDocumentParser(converter=lambda _req: (_ for _ in ()).throw(RuntimeError("Parse boom")))
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        storage=FakeStorage(),
    )

    dispatcher._execute_pipeline(run_id)

    assert cleanup_called["value"] is True

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
    assert run is not None
    assert run.status == "failed"


def test_pipeline_runner_executes_all_stages_end_to_end(dispatcher_env) -> None:
    """PipelineRunner.run executes parse -> persist -> quality and marks run completed."""
    run_id = dispatcher_env["run_id"]
    document_id = dispatcher_env["document_id"]

    test_artifact = _make_test_artifact(document_id)
    parser = DoclingDocumentParser(converter=lambda _req: test_artifact)
    runner = PipelineRunner(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        ocr_service=StubOcrService(
            result=OcrResult(
                applied=True,
                engine="tesseract",
                provider="docling-local",
                status="applied",
                page_numbers=[1],
                notes=["ocr used for first page"],
            )
        ),
    )

    runner.run(run_id)

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
    assert run is not None
    assert run.status == "completed"

    stages = get_stages_for_run(run_id=run_id)
    assert len(stages) == 7
    for stage in stages:
        assert stage.status == "completed", f"Stage {stage.stage_name} is {stage.status}, expected completed"


def test_pipeline_runner_marks_run_failed_on_error(dispatcher_env) -> None:
    """PipelineRunner.run marks the run as failed when a stage raises."""
    run_id = dispatcher_env["run_id"]

    parser = DoclingDocumentParser(converter=lambda _req: (_ for _ in ()).throw(RuntimeError("Runner boom")))
    runner = PipelineRunner(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
    )

    runner.run(run_id)

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
    assert run is not None
    assert run.status == "failed"


def test_in_process_dispatcher_delegates_to_pipeline_runner(dispatcher_env) -> None:
    """InProcessDispatcher._execute_pipeline delegates to PipelineRunner.run."""
    run_id = dispatcher_env["run_id"]
    calls: list = []

    class RunnerSpy:
        def run(self, run_id_arg) -> None:
            calls.append(run_id_arg)

    dispatcher = InProcessDispatcher(
        parser=DoclingDocumentParser(converter=lambda _req: _make_test_artifact(dispatcher_env["document_id"])),
        parser_backend="docling-local",
        parser_profile="local-cpu",
        runner=RunnerSpy(),
    )

    dispatcher._execute_pipeline(run_id)

    assert len(calls) == 1
    assert calls[0] == run_id


def test_pipeline_runner_materializes_and_cleans_up(dispatcher_env, tmp_path: Path) -> None:
    """PipelineRunner.run materializes storage and cleans up after completion."""
    materialized_file = tmp_path / "runner-materialized.txt"
    materialized_file.write_text("hello")
    cleanup_called = {"value": False}

    class FakeStorage(StorageAdapter):
        def materialize_for_read(self, *, object_key: str) -> MaterializedObject:
            def _cleanup() -> None:
                cleanup_called["value"] = True
            return MaterializedObject(local_path=materialized_file, cleanup=_cleanup)

    run_id = dispatcher_env["run_id"]
    document_id = dispatcher_env["document_id"]

    test_artifact = _make_test_artifact(document_id)
    parser = DoclingDocumentParser(converter=lambda _req: test_artifact)
    runner = PipelineRunner(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        storage=FakeStorage(),
    )

    runner.run(run_id)

    assert cleanup_called["value"] is True

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
    assert run is not None
    assert run.status == "completed"


# --- Chunk stage tests ---


def test_pipeline_runner_includes_chunk_stage():
    """PipelineRunner STAGE_NAMES must include 'chunk'."""
    from app.workflows.pipeline_runner import STAGE_NAMES
    assert "chunk" in STAGE_NAMES


def test_run_chunk_stage_produces_chunks(seeded_env):
    """run_chunk_stage should produce chunks from a parsed artifact."""
    from app.workflows.stages import run_chunk_stage

    run_id = seeded_env["run_id"]
    document_id = seeded_env["document_id"]

    # First parse to get an artifact
    parse_stage_id = seeded_env["stage_ids"]["parse"]
    test_artifact = _make_test_artifact(document_id)
    parser = DoclingDocumentParser(converter=lambda _req: test_artifact)
    ocr_service = StubOcrService(
        result=OcrResult(
            applied=False,
            engine="none",
            provider="docling-local",
            status="not-applied",
            page_numbers=[],
            notes=[],
        )
    )
    run_parse_stage(
        run_id=run_id,
        stage_id=parse_stage_id,
        document_id=document_id,
        object_key="documents/dispatcher.txt",
        content_type="text/plain",
        profile="local-cpu",
        parser_backend="docling-local",
        parser=parser,
        ocr_service=ocr_service,
    )

    # Now create a chunk stage and run it
    stages = ensure_ingestion_stages(
        run_id=run_id,
        tenant_id=seeded_env["tenant_id"],
        stage_names=["chunk"],
    )
    chunk_stage_id = stages[0].id

    chunks = run_chunk_stage(
        run_id=run_id,
        stage_id=chunk_stage_id,
        document_id=document_id,
        artifact=test_artifact,
        profile="loose",
    )

    assert chunks is not None
    assert len(chunks) > 0
    assert all(c.document_id == document_id for c in chunks)


def _make_hierarchical_artifact(document_id) -> ParsedArtifact:
    """A two-section page shaped like the F0 adapter's rich block output."""
    ch = ["Statistics Primer", "Chapter 1: Distributions"]
    s11 = ch + ["1.1 The Normal Distribution"]
    s12 = ch + ["1.2 The Poisson Distribution"]
    normal = "The normal distribution is a continuous symmetric distribution described by its mean and variance."
    poisson = "The Poisson distribution models counts of independent events occurring at a constant average rate."
    blocks = [
        ParsedBlock(block_type="title", text="Statistics Primer", heading_path=["Statistics Primer"], level=0),
        ParsedBlock(block_type="section_header", text="Chapter 1: Distributions", heading_path=ch, level=1),
        ParsedBlock(block_type="section_header", text="1.1 The Normal Distribution", heading_path=s11, level=2),
        ParsedBlock(block_type="text", text=normal, heading_path=s11),
        ParsedBlock(block_type="section_header", text="1.2 The Poisson Distribution", heading_path=s12, level=2),
        ParsedBlock(block_type="text", text=poisson, heading_path=s12),
    ]
    prose = "\n\n".join(b.text for b in blocks if b.text and b.block_type == "text")
    return ParsedArtifact(
        document_id=document_id,
        pages=[ParsedPage(page_number=1, text=prose, blocks=blocks)],
        tables=[],
        provenance=ParserProvenance(parser_backend="docling-local", parser_version="2.102.1", profile="local-cpu"),
    )


def _run_chunk_with_profile(seeded_env, artifact, profile: str):
    from app.workflows.stages import run_chunk_stage

    stages = ensure_ingestion_stages(
        run_id=seeded_env["run_id"],
        tenant_id=seeded_env["tenant_id"],
        stage_names=["chunk"],
    )
    chunks = run_chunk_stage(
        run_id=seeded_env["run_id"],
        stage_id=stages[0].id,
        document_id=seeded_env["document_id"],
        artifact=artifact,
        profile=profile,
    )
    chunk_stage = next(s for s in get_stages_for_run(run_id=seeded_env["run_id"]) if s.stage_name == "chunk")
    return chunks, chunk_stage


def test_run_chunk_stage_routes_book_profile_to_book_chunker(seeded_env) -> None:
    """A book-profile run produces hierarchy-aware section parents (ADR-0012)."""
    artifact = _make_hierarchical_artifact(seeded_env["document_id"])
    chunks, chunk_stage = _run_chunk_with_profile(seeded_env, artifact, "book")

    assert chunks is not None
    section_parents = [c for c in chunks if c.parent_id is None and c.unit_type == "section"]
    assert len(section_parents) == 2  # one per content-bearing section
    breadcrumbs = {tuple(p.heading_path) for p in section_parents}
    assert ("Statistics Primer", "Chapter 1: Distributions", "1.1 The Normal Distribution") in breadcrumbs
    assert chunk_stage.details["profile"] == "book"


def test_run_chunk_stage_loose_profile_does_not_use_book_chunker(seeded_env) -> None:
    """The same hierarchical artifact under the loose profile yields the flat
    chunker's 'document' root and no 'section' parents — proving the persisted
    profile (not block shape) selects the chunker."""
    artifact = _make_hierarchical_artifact(seeded_env["document_id"])
    chunks, chunk_stage = _run_chunk_with_profile(seeded_env, artifact, "loose")

    assert chunks is not None
    assert not any(c.unit_type == "section" for c in chunks)  # 'section' is book-only
    assert any(c.parent_id is None and c.unit_type == "document" for c in chunks)
    assert chunk_stage.details["profile"] == "loose"


def test_run_chunk_stage_unknown_profile_defaults_to_loose(seeded_env) -> None:
    """A malformed/legacy profile value must not crash the pipeline — it falls
    back to the loose chunker."""
    artifact = _make_hierarchical_artifact(seeded_env["document_id"])
    chunks, chunk_stage = _run_chunk_with_profile(seeded_env, artifact, "nonsense")

    assert chunks is not None
    assert not any(c.unit_type == "section" for c in chunks)
    assert chunk_stage.details["profile"] == "loose"


def test_get_document_index_acl_metadata_returns_real_group_ids(seeded_env) -> None:
    document_id = seeded_env["document_id"]
    tenant_id = seeded_env["tenant_id"]
    owner_user_id = seeded_env["user_id"]
    group_id = uuid4()

    with session_factory() as session:
        acl_grant = session.scalar(select(AclGrant).where(AclGrant.document_id == document_id))
        assert acl_grant is not None
        session.add(Group(id=group_id, tenant_id=tenant_id, name="indexed-group"))
        session.add(AclAllowedGroup(acl_grant_id=acl_grant.id, group_id=group_id))
        session.commit()

    metadata = get_document_index_acl_metadata(document_id=document_id)

    assert metadata["tenant_id"] == str(tenant_id)
    assert metadata["group_ids"] == [str(group_id)]
    assert metadata["allowed_group_ids"] == [str(group_id)]
    assert metadata["allowed_user_ids"] == [str(owner_user_id)]
    assert metadata["visibility"] == "private"
    assert metadata["sensitivity"] == "internal"
    assert metadata["sensitivity_rank"] == 200
    assert metadata["acl_policy_id"]
    assert metadata["acl_policy_version"] == 1
    assert metadata["allowed_role_ids"] == []
    assert metadata["allowed_org_unit_ids"] == []
    assert metadata["allowed_project_ids"] == []


def test_pipeline_runner_passes_real_acl_metadata_to_indexers(seeded_env) -> None:
    run_id = seeded_env["run_id"]
    document_id = seeded_env["document_id"]
    tenant_id = seeded_env["tenant_id"]
    group_id = uuid4()

    with session_factory() as session:
        acl_grant = session.scalar(select(AclGrant).where(AclGrant.document_id == document_id))
        assert acl_grant is not None
        session.add(Group(id=group_id, tenant_id=tenant_id, name="pipeline-group"))
        session.add(AclAllowedGroup(acl_grant_id=acl_grant.id, group_id=group_id))
        session.commit()

    artifact = ParsedArtifact(
        document_id=document_id,
        pages=[
            ParsedPage(
                page_number=1,
                text=(
                    "First paragraph with enough text to exceed the minimum threshold.\n\n"
                    "Second paragraph also with sufficient length to be included as a chunk."
                ),
                blocks=[],
            )
        ],
        tables=[],
        provenance=ParserProvenance(
            parser_backend="docling-local",
            parser_version="1.0",
            profile="local-cpu",
        ),
    )

    class VectorIndexerSpy:
        def __init__(self) -> None:
            self.acl_metadata: dict | None = None

        def upsert(self, *, chunks, embeddings, acl_metadata: dict) -> int:
            self.acl_metadata = acl_metadata
            return len(chunks)

    class LexicalIndexerSpy:
        def __init__(self) -> None:
            self.acl_metadata: dict | None = None

        def upsert(self, *, chunks, acl_metadata: dict) -> int:
            self.acl_metadata = acl_metadata
            return len(chunks)

    vector_indexer = VectorIndexerSpy()
    lexical_indexer = LexicalIndexerSpy()
    runner = PipelineRunner(
        parser=DoclingDocumentParser(converter=lambda _req: artifact),
        parser_backend="docling-local",
        parser_profile="local-cpu",
        vector_indexer=vector_indexer,
        lexical_indexer=lexical_indexer,
    )

    runner.run(run_id)

    assert vector_indexer.acl_metadata is not None
    assert lexical_indexer.acl_metadata is not None
    assert vector_indexer.acl_metadata["group_ids"] == [str(group_id)]
    assert lexical_indexer.acl_metadata["group_ids"] == [str(group_id)]
    assert vector_indexer.acl_metadata["tenant_id"] == str(tenant_id)
    assert lexical_indexer.acl_metadata["visibility"] == "private"
    assert vector_indexer.acl_metadata["acl_policy_id"]
    assert vector_indexer.acl_metadata["acl_policy_version"] == 1
    assert lexical_indexer.acl_metadata["sensitivity_rank"] == 200
