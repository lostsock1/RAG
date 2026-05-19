from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, func, insert, select
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.db.base import session_factory
from app.db.acl_models import AclAllowedUser, AclGrant
from app.db.models.document import Document
from app.db.models.ingestion import IngestionRun, IngestionStage, ParsedArtifact as ParsedArtifactRecord, QualityReport
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.repositories.ingestion import (
    create_ingestion_stages,
    ensure_ingestion_stages,
    get_stages_for_run,
    prepare_ingestion_run_for_retry,
    recover_orphaned_runs,
    store_parsed_artifact,
    try_claim_ingestion_run,
    update_run_status,
    update_stage_status,
)
from app.schemas.parsed_artifacts import OcrProvenance, ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance


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
                parser_backend="docling-local",
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
        provenance=ParserProvenance(
            parser_backend="docling-local",
            parser_version="2.x",
            profile="local-gpu",
            ocr=OcrProvenance(
                applied=True,
                engine="tesseract",
                provider="docling-local",
                status="applied",
                page_numbers=[1],
                notes=["ocr used for scanned page"],
            ),
        ),
    )

    stored = store_parsed_artifact(run_id=seeded_run.id, artifact=artifact)

    assert stored.run_id == seeded_run.id

    with session_factory() as session:
        stored_record = session.scalar(select(ParsedArtifactRecord).where(ParsedArtifactRecord.id == stored.id))
        assert stored_record is not None
        assert stored_record.artifact_json["provenance"]["parser_backend"] == "docling-local"

        report = session.scalar(select(QualityReport).where(QualityReport.run_id == seeded_run.id))
        assert report is not None
        assert report.summary["table_count"] == 1
        assert report.summary["page_count"] == 1
        assert report.summary["ocr_page_count"] == 1
        assert report.raw_report_text is not None
        assert '"parser_profile":"local-gpu"' in report.raw_report_text
        assert '"status":"applied"' in report.raw_report_text


def test_store_parsed_artifact_replaces_existing_records_for_same_run(seeded_run: IngestionRun) -> None:
    first_artifact = ParsedArtifact(
        document_id=seeded_run.document_id,
        pages=[ParsedPage(page_number=1, text="hello world", blocks=[])],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 10, 10], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="docling-local", parser_version="2.x", profile="local-gpu"),
    )
    second_artifact = ParsedArtifact(
        document_id=seeded_run.document_id,
        pages=[ParsedPage(page_number=1, text="hello again", blocks=[])],
        tables=[],
        provenance=ParserProvenance(parser_backend="docling-local", parser_version="2.x", profile="local-gpu"),
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
                "parser_backend": "docling-local",
                "parser_version": "2.x",
                "profile": "local-gpu",
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


def test_ensure_ingestion_stages_reuses_existing_rows(seeded_run: IngestionRun) -> None:
    stage_names = ["parse", "persist_artifact", "quality_report"]

    first = ensure_ingestion_stages(
        run_id=seeded_run.id,
        tenant_id=seeded_run.tenant_id,
        stage_names=stage_names,
    )
    second = ensure_ingestion_stages(
        run_id=seeded_run.id,
        tenant_id=seeded_run.tenant_id,
        stage_names=stage_names,
    )

    assert [stage.id for stage in second] == [stage.id for stage in first]

    with session_factory() as session:
        count = session.scalar(select(func.count()).select_from(IngestionStage).where(IngestionStage.run_id == seeded_run.id))

    assert count == 3


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


def test_try_claim_ingestion_run_transitions_queued_run_once(seeded_run: IngestionRun) -> None:
    claimed = try_claim_ingestion_run(run_id=seeded_run.id)
    skipped = try_claim_ingestion_run(run_id=seeded_run.id)

    assert claimed is not None
    assert claimed.status == "running"
    assert skipped is None


def test_prepare_ingestion_run_for_retry_resets_failed_and_running_stages(seeded_run: IngestionRun) -> None:
    stages = ensure_ingestion_stages(
        run_id=seeded_run.id,
        tenant_id=seeded_run.tenant_id,
        stage_names=["parse", "persist_artifact", "quality_report"],
    )
    update_run_status(run_id=seeded_run.id, status="failed")
    update_stage_status(stage_id=stages[0].id, status="completed")
    update_stage_status(stage_id=stages[1].id, status="failed", details={"error": "persist failed"})
    update_stage_status(stage_id=stages[2].id, status="running", details={"step": "quality"})

    run = prepare_ingestion_run_for_retry(run_id=seeded_run.id)

    assert run.status == "queued"
    refreshed = get_stages_for_run(run_id=seeded_run.id)
    assert [stage.status for stage in refreshed] == ["completed", "queued", "queued"]
    assert refreshed[1].details["retry_reset_reason"] == "manual_retry"
    assert refreshed[2].details["retry_reset_reason"] == "manual_retry"


def test_recover_orphaned_runs_resets_running_to_queued(seeded_run: IngestionRun) -> None:
    stages = ensure_ingestion_stages(
        run_id=seeded_run.id,
        tenant_id=seeded_run.tenant_id,
        stage_names=["parse", "persist_artifact", "quality_report"],
    )
    update_run_status(run_id=seeded_run.id, status="running")
    update_stage_status(stage_id=stages[0].id, status="completed")
    update_stage_status(stage_id=stages[1].id, status="running", details={"step": "persist"})
    update_stage_status(stage_id=stages[2].id, status="running", details={"step": "quality"})

    count = recover_orphaned_runs()
    assert count == 1

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == seeded_run.id))
        assert run is not None
        assert run.status == "queued"

        refreshed_stages = session.scalars(
            select(IngestionStage)
            .where(IngestionStage.run_id == seeded_run.id)
            .order_by(IngestionStage.created_at.asc())
        ).all()

        assert [stage.status for stage in refreshed_stages] == ["completed", "queued", "queued"]
        assert refreshed_stages[1].details["recovery_reset_reason"] == "startup_recovery"
        assert refreshed_stages[2].details["recovery_reset_reason"] == "startup_recovery"
