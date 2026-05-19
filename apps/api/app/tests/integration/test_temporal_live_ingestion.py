from __future__ import annotations

from hashlib import sha256
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
from app.db.models.ingestion import IngestionRun, IngestionStage
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.repositories.documents import create_document_with_owner_acl
from app.repositories.ingestion import create_ingestion_run
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParserProvenance
from app.workflows.temporal_worker import temporal_server_is_available


@pytest.mark.anyio
async def test_temporal_live_ingestion_completes_when_server_available() -> None:
    if not await temporal_server_is_available(host_port="127.0.0.1:7233", namespace="default"):
        pytest.skip("Temporal server is not reachable at 127.0.0.1:7233.")

    client_module = pytest.importorskip("temporalio.client")
    worker_module = pytest.importorskip("temporalio.worker")
    Client = client_module.Client
    Worker = worker_module.Worker

    from app.services.parsers.docling_backend import DoclingDocumentParser
    from app.services.storage import LocalFilesystemStorageAdapter
    from app.workflows.pipeline_runner import PipelineRunner
    from app.workflows.temporal_dispatcher import TemporalDispatcher
    from app.workflows.temporal_workflow import IngestionWorkflow, build_ingestion_activity

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        database_url = f"sqlite:///{tmp_path / 'temporal_live.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        tenant_id = uuid4()
        user_id = uuid4()
        source_bytes = b"temporal local proof content"
        source_hash = sha256(source_bytes).hexdigest()
        storage_root = tmp_path / "storage"
        storage = LocalFilesystemStorageAdapter(storage_root)
        object_key = "documents/live-proof.txt"
        storage.put_object(object_key=object_key, content=source_bytes, content_type="text/plain")

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Temporal Tenant", slug="temporal-tenant"))
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email="temporal@example.com",
                    display_name="Temporal Tester",
                    roles=["editor"],
                )
            )
            session.commit()

        document = create_document_with_owner_acl(
            tenant_id=tenant_id,
            owner_user_id=user_id,
            title="Temporal Live Proof",
            source_type="loose_document",
            source_hash=source_hash,
            file_name="live-proof.txt",
            file_size_bytes=len(source_bytes),
            object_key=object_key,
        )
        run = create_ingestion_run(
            document_id=document.id,
            tenant_id=tenant_id,
            parser_backend="docling-local",
            source_hash=source_hash,
        )

        artifact = ParsedArtifact(
            document_id=document.id,
            pages=[ParsedPage(page_number=1, text="temporal local proof content", blocks=[])],
            tables=[],
            provenance=ParserProvenance(
                parser_backend="docling-local",
                parser_version="1.0.0",
                profile="local-cpu",
            ),
        )
        parser = DoclingDocumentParser(converter=lambda request: artifact)
        runner = PipelineRunner(
            parser=parser,
            parser_backend="docling-local",
            parser_profile="local-cpu",
            storage=storage,
        )

        client = await Client.connect("127.0.0.1:7233", namespace="default")
        task_queue = f"uber-rag-live-{uuid4()}"

        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[IngestionWorkflow],
            activities=[build_ingestion_activity(runner)],
        ):
            dispatcher = TemporalDispatcher(
                host_port="127.0.0.1:7233",
                namespace="default",
                task_queue=task_queue,
                client=client,
            )
            await dispatcher.dispatch(run.id)
            handle = client.get_workflow_handle(f"ingestion-run:{run.id}")
            import asyncio

            result = await asyncio.wait_for(handle.result(), timeout=60)

        assert result == str(run.id)

        with session_factory() as session:
            refreshed_run = session.scalar(select(IngestionRun).where(IngestionRun.id == run.id))
            assert refreshed_run is not None
            assert refreshed_run.status == "completed"

            stages = list(
                session.scalars(
                    select(IngestionStage)
                    .where(IngestionStage.run_id == run.id)
                    .order_by(IngestionStage.created_at.asc())
                ).all()
            )
            assert len(stages) == 7
            assert all(stage.status == "completed" for stage in stages)

        session_factory.configure(bind=None)
        engine.dispose()
