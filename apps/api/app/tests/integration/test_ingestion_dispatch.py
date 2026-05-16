from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.request_context import RequestContext
from app.core.security import get_request_context
from app.db.base import session_factory
from app.db.models.ingestion import IngestionRun, IngestionStage
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.main import app
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParserProvenance
from app.services.parsers.docling_backend import DoclingDocumentParser
from app.services.storage import S3CompatibleStorageAdapter
from app.workflows.dispatcher import InProcessDispatcher


class StorageStub:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, *, object_key: str, content: bytes, content_type: str) -> None:
        self.objects[object_key] = content


class FakeS3ClientWithDownload:
    """Fake S3 client that stores uploaded bytes and serves them back via download_file."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: object) -> None:
        key = kwargs["Key"]
        body = kwargs["Body"]
        self.objects[key] = body if isinstance(body, bytes) else b""

    def download_file(self, Bucket: str, Key: str, Filename: str) -> None:
        from pathlib import Path as _Path

        content = self.objects.get(Key, b"")
        _Path(Filename).write_bytes(content)


@pytest.fixture()
def auth_context() -> RequestContext:
    return RequestContext(
        tenant_id=str(uuid4()),
        user_id=str(uuid4()),
        group_ids=[],
        roles=["editor"],
        scopes=["documents:write", "documents:read"],
    )


@pytest.fixture()
def client(auth_context: RequestContext):
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'dispatch_e2e.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=UUID(auth_context.tenant_id), name="T", slug="t"))
            session.add(
                User(
                    id=UUID(auth_context.user_id),
                    tenant_id=UUID(auth_context.tenant_id),
                    email="u@t.com",
                    display_name="U",
                    roles=auth_context.roles,
                )
            )
            session.commit()

        # Create a dispatcher with a test parser that returns a predictable artifact
        expected_artifact = ParsedArtifact(
            document_id=uuid4(),  # will be overwritten by the converter at parse time
            pages=[ParsedPage(page_number=1, text="test content", blocks=[])],
            tables=[],
            provenance=ParserProvenance(
                parser_backend="docling", parser_version="1.0.0", profile="local-cpu"
            ),
        )
        parser = DoclingDocumentParser(converter=lambda req: expected_artifact)
        dispatcher = InProcessDispatcher(
            parser=parser,
            parser_backend="docling-local",
            parser_profile="local-cpu",
        )

        app.dependency_overrides[get_request_context] = lambda: auth_context
        app.state.document_storage = StorageStub()
        # Do NOT set app.state.dispatcher here — the route's async dispatch
        # uses asyncio.create_task which has non-deterministic completion in
        # TestClient's sync context.  The test calls _execute_pipeline directly
        # to ensure deterministic behaviour.
        app.state._test_dispatcher = dispatcher

        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()
            for attr in ("document_storage", "_test_dispatcher"):
                if hasattr(app.state, attr):
                    delattr(app.state, attr)
            session_factory.configure(bind=None)
            engine.dispose()


def test_upload_triggers_ingestion_dispatch_to_completed(client):
    response = client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": "Bearer test-token"},
        files={"file": ("doc.txt", b"test content", "text/plain")},
        data={"title": "Test Doc", "source_type": "loose_document"},
    )

    assert response.status_code == 201
    payload = response.json()
    run_id = UUID(payload["ingestion_run_id"])

    # The route does not dispatch (no app.state.dispatcher set in test).
    # Run the pipeline synchronously to verify the full dispatch pipeline.
    dispatcher = app.state._test_dispatcher
    dispatcher._execute_pipeline(run_id)

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        assert run.status == "completed"

        stages = list(
            session.scalars(
                select(IngestionStage)
                .where(IngestionStage.run_id == run_id)
                .order_by(IngestionStage.created_at.asc())
            ).all()
        )
        assert len(stages) == 3
        assert all(s.status == "completed" for s in stages)
        assert stages[0].stage_name == "parse"
        assert stages[0].details["parser_backend"] == "docling-local"
        assert stages[1].stage_name == "persist_artifact"
        assert stages[2].stage_name == "quality_report"


def test_upload_and_parse_through_s3_compatible_storage(client):
    """Upload stores to fake S3, dispatcher materializes a temp file, parser runs, run completes."""
    fake_s3 = FakeS3ClientWithDownload()
    storage = S3CompatibleStorageAdapter(
        endpoint_url="http://fake-s3:8333",
        access_key="test",
        secret_key="test",
        bucket="uber-rag-documents",
        region="us-east-1",
        client=fake_s3,
    )

    # Replace the storage stub with the fake S3 adapter
    app.state.document_storage = storage

    expected_artifact = ParsedArtifact(
        document_id=uuid4(),
        pages=[ParsedPage(page_number=1, text="s3 materialized content", blocks=[])],
        tables=[],
        provenance=ParserProvenance(
            parser_backend="docling", parser_version="1.0.0", profile="local-cpu"
        ),
    )
    parser = DoclingDocumentParser(converter=lambda req: expected_artifact)
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        storage=storage,
    )
    app.state._test_dispatcher = dispatcher

    response = client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": "Bearer test-token"},
        files={"file": ("s3-doc.txt", b"uploaded via s3", "text/plain")},
        data={"title": "S3 Doc", "source_type": "loose_document"},
    )

    assert response.status_code == 201
    run_id = UUID(response.json()["ingestion_run_id"])

    # Verify the file was stored in fake S3
    assert len(fake_s3.objects) > 0

    # Run the pipeline synchronously
    dispatcher._execute_pipeline(run_id)

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        assert run.status == "completed"

        stages = list(
            session.scalars(
                select(IngestionStage)
                .where(IngestionStage.run_id == run_id)
                .order_by(IngestionStage.created_at.asc())
            ).all()
        )
        assert len(stages) == 3
        assert all(s.status == "completed" for s in stages)
        assert stages[0].stage_name == "parse"
        assert stages[0].details["parser_backend"] == "docling-local"
