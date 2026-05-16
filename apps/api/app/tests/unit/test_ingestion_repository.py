from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.db.base import session_factory
from app.db.models.acl import AclAllowedUser, AclGrant
from app.db.models.document import Document
from app.db.models.ingestion import IngestionRun, IngestionStage, ParsedArtifact as ParsedArtifactRecord, QualityReport
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.repositories.ingestion import (
    create_ingestion_stages,
    get_stages_for_run,
    recover_orphaned_runs,
    store_parsed_artifact,
    update_run_status,
    update_stage_status,
)
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance


@pytest.fixture()
def seeded_run():
    tenant_id = uuid4()
    user_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'ingestion-repository.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Tenant", slug="tenant-ingestion-repository"))
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email="user@example.com",
                    display_name="User",
                    roles=["editor"],
                )
            )
            document = Document(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                title="Repository Test",
                source_type="loose_document",
                source_hash="hash-repository",
                file_name="repository.txt",
                file_size_bytes=1,
                object_key="documents/repository.txt",
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

        try:
            yield run
        finally:
            session_factory.configure(bind=None)
            engine.dispose()


def test_store_parsed_artifact_and_quality_report(seeded_run: IngestionRun) -> None:
    artifact = ParsedArtifact(
        document_id=seeded_run.document_id,
        pages=[ParsedPage(page_number=1, text="hello world", blocks=[])],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 10, 10], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="docling", parser_version="2.x", profile="gpu-local"),
    )

    stored = store_parsed_artifact(run_id=seeded_run.id, artifact=artifact)

    assert stored.run_id == seeded_run.id

    with session_factory() as session:
        stored_record = session.scalar(select(ParsedArtifactRecord).where(ParsedArtifactRecord.id == stored.id))
        assert stored_record is not None
        assert stored_record.artifact_json["provenance"]["parser_backend"] == "docling"

        report = session.scalar(select(QualityReport).where(QualityReport.run_id == seeded_run.id))
        assert report is not None
        assert report.summary["table_count"] == 1
        assert report.summary["page_count"] == 1


def test_store_parsed_artifact_replaces_existing_records_for_same_run(seeded_run: IngestionRun) -> None:
    first_artifact = ParsedArtifact(
        document_id=seeded_run.document_id,
        pages=[ParsedPage(page_number=1, text="hello world", blocks=[])],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 10, 10], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="docling", parser_version="2.x", profile="gpu-local"),
    )
    second_artifact = ParsedArtifact(
        document_id=seeded_run.document_id,
        pages=[ParsedPage(page_number=1, text="hello again", blocks=[])],
        tables=[],
        provenance=ParserProvenance(parser_backend="docling", parser_version="2.x", profile="gpu-local"),
    )

    first_record = store_parsed_artifact(run_id=seeded_run.id, artifact=first_artifact)
    second_record = store_parsed_artifact(run_id=seeded_run.id, artifact=second_artifact)

    assert second_record.id == first_record.id

    with session_factory() as session:
        parsed_artifacts = session.scalars(
            select(ParsedArtifactRecord).where(ParsedArtifactRecord.run_id == seeded_run.id)
        ).all()
        quality_reports = session.scalars(
            select(QualityReport).where(QualityReport.run_id == seeded_run.id)
        ).all()

        assert len(parsed_artifacts) == 1
        assert parsed_artifacts[0].artifact_json["pages"][0]["text"] == "hello again"
        assert len(quality_reports) == 1
        assert quality_reports[0].summary["table_count"] == 0


def test_ingestion_artifact_tables_enforce_one_record_per_run(seeded_run: IngestionRun) -> None:
    artifact_payload = {
        "document_id": str(seeded_run.document_id),
        "pages": [],
        "tables": [],
        "provenance": {
            "parser_backend": "docling",
            "parser_version": "2.x",
            "profile": "gpu-local",
        },
    }

    with session_factory() as session:
        session.execute(
            insert(ParsedArtifactRecord).values(
                run_id=seeded_run.id,
                tenant_id=seeded_run.tenant_id,
                artifact_type="structured",
                artifact_json=artifact_payload,
                artifact_hash="hash-1",
            )
        )
        session.commit()

        with pytest.raises(IntegrityError):
            session.execute(
                insert(ParsedArtifactRecord).values(
                    run_id=seeded_run.id,
                    tenant_id=seeded_run.tenant_id,
                    artifact_type="structured",
                    artifact_json=artifact_payload,
                    artifact_hash="hash-2",
                )
            )
            session.commit()

        session.rollback()

        session.execute(
            insert(QualityReport).values(
                run_id=seeded_run.id,
                tenant_id=seeded_run.tenant_id,
                quality_score="1.00",
                summary={"page_count": 0, "table_count": 0, "non_empty_text_pages": 0},
                warnings=[],
                raw_report_text=None,
            )
        )
        session.commit()

        with pytest.raises(IntegrityError):
            session.execute(
                insert(QualityReport).values(
                    run_id=seeded_run.id,
                    tenant_id=seeded_run.tenant_id,
                    quality_score="0.50",
                    summary={"page_count": 1, "table_count": 1, "non_empty_text_pages": 1},
                    warnings=[],
                    raw_report_text=None,
                )
            )
            session.commit()


# ---------------------------------------------------------------------------
# Stage / run status helpers
# ---------------------------------------------------------------------------


def test_create_ingestion_stages_creates_three_records(seeded_run: IngestionRun) -> None:
    stage_names = ["parse", "chunk", "embed"]
    stages = create_ingestion_stages(
        run_id=seeded_run.id,
        tenant_id=seeded_run.tenant_id,
        stage_names=stage_names,
    )

    assert len(stages) == 3
    for stage in stages:
        assert stage.status == "queued"
        assert stage.run_id == seeded_run.id
        assert stage.tenant_id == seeded_run.tenant_id
    assert [s.stage_name for s in stages] == stage_names

    # Verify via get_stages_for_run
    fetched = get_stages_for_run(run_id=seeded_run.id)
    assert len(fetched) == 3
    assert [s.stage_name for s in fetched] == stage_names


def test_update_stage_status_sets_status_and_details(seeded_run: IngestionRun) -> None:
    stages = create_ingestion_stages(
        run_id=seeded_run.id,
        tenant_id=seeded_run.tenant_id,
        stage_names=["parse"],
    )
    stage = stages[0]

    update_stage_status(stage_id=stage.id, status="running")
    fetched = get_stages_for_run(run_id=seeded_run.id)
    assert fetched[0].status == "running"

    update_stage_status(
        stage_id=stage.id,
        status="completed",
        details={"duration_s": 12.5, "chunks_created": 42},
    )
    fetched = get_stages_for_run(run_id=seeded_run.id)
    assert fetched[0].status == "completed"
    assert fetched[0].details["duration_s"] == 12.5
    assert fetched[0].details["chunks_created"] == 42


def test_update_run_status(seeded_run: IngestionRun) -> None:
    assert seeded_run.status == "queued"

    update_run_status(run_id=seeded_run.id, status="running")

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == seeded_run.id))
        assert run is not None
        assert run.status == "running"


def test_recover_orphaned_runs_resets_running_to_queued(seeded_run: IngestionRun) -> None:
    update_run_status(run_id=seeded_run.id, status="running")

    count = recover_orphaned_runs()
    assert count == 1

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == seeded_run.id))
        assert run is not None
        assert run.status == "queued"
