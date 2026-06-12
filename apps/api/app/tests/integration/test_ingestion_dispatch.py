from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import cast
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
from app.db.models.chunk import Chunk as ChunkModel
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

    def put_object_stream(self, *, object_key: str, fp, content_type: str, content_length: int) -> None:
        self.objects[object_key] = fp.read()

    def materialize_for_read(self, *, object_key: str):
        from app.services.storage import MaterializedObject
        from tempfile import NamedTemporaryFile as _NTF
        from pathlib import Path as _Path

        content = self.objects.get(object_key, b"")
        with _NTF(delete=False) as tmp:
            tmp_path = _Path(tmp.name)
            tmp.write(content)

        def _cleanup():
            if tmp_path.exists():
                tmp_path.unlink()

        return MaterializedObject(local_path=tmp_path, cleanup=_cleanup)


class FakeS3ClientWithDownload:
    """Fake S3 client that stores uploaded bytes and serves them back via download_file."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: object) -> None:
        key = cast(str, kwargs["Key"])
        body = kwargs["Body"]
        self.objects[key] = body if isinstance(body, bytes) else b""

    def upload_fileobj(self, fp, bucket: str, key: str, ExtraArgs: dict | None = None) -> None:
        self.objects[key] = fp.read()

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
                parser_backend="docling-local", parser_version="1.0.0", profile="local-cpu"
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
        assert len(stages) == 7
        assert all(s.status == "completed" for s in stages)
        assert stages[0].stage_name == "parse"
        assert stages[0].details["parser_backend"] == "docling-local"
        assert stages[1].stage_name == "persist_artifact"
        assert stages[2].stage_name == "chunk"
        assert stages[3].stage_name == "embed"
        assert stages[4].stage_name == "index_qdrant"
        assert stages[5].stage_name == "index_opensearch"
        assert stages[6].stage_name == "quality_report"


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
            parser_backend="docling-local", parser_version="1.0.0", profile="local-cpu"
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
        assert len(stages) == 7
        assert all(s.status == "completed" for s in stages)
        assert stages[0].stage_name == "parse"
        assert stages[0].details["parser_backend"] == "docling-local"


def test_full_pipeline_produces_chunks_in_db(client):
    """Upload -> parse -> chunk -> verify chunks are persisted with parent-child relationships."""
    # Override the dispatcher with a parser that returns a multi-paragraph artifact
    rich_artifact = ParsedArtifact(
        document_id=uuid4(),
        pages=[
            ParsedPage(page_number=1, text="First paragraph with enough text to exceed the minimum threshold.\n\nSecond paragraph also with sufficient length to be included as a chunk.", blocks=[]),
            ParsedPage(page_number=2, text="Third paragraph on page two with adequate length for chunking.", blocks=[]),
        ],
        tables=[],
        provenance=ParserProvenance(
            parser_backend="docling-local", parser_version="1.0.0", profile="local-cpu"
        ),
    )
    parser = DoclingDocumentParser(converter=lambda req: rich_artifact)
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
    )
    app.state._test_dispatcher = dispatcher

    response = client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": "Bearer test-token"},
        files={"file": ("chunked-doc.txt", b"paragraph one\n\nparagraph two", "text/plain")},
        data={"title": "Chunked Doc", "source_type": "loose_document"},
    )

    assert response.status_code == 201
    run_id = UUID(response.json()["ingestion_run_id"])

    # Run the pipeline synchronously
    dispatcher._execute_pipeline(run_id)

    with session_factory() as session:
        # Verify run completed
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        assert run.status == "completed"

        # Verify chunk stage completed
        chunk_stage = session.scalar(
            select(IngestionStage).where(
                IngestionStage.run_id == run_id,
                IngestionStage.stage_name == "chunk",
            )
        )
        assert chunk_stage is not None
        assert chunk_stage.status == "completed"
        assert chunk_stage.details["chunk_count"] > 0

        # Verify chunks exist in DB
        document_id = run.document_id
        chunks = list(
            session.scalars(
                select(ChunkModel)
                .where(ChunkModel.document_id == document_id)
                .order_by(ChunkModel.chunk_index.asc())
            ).all()
        )
        assert len(chunks) > 0

        # Verify parent-child structure
        parents = [c for c in chunks if c.parent_id is None]
        leaves = [c for c in chunks if c.parent_id is not None]
        assert len(parents) >= 1, "Expected at least one parent chunk"
        assert len(leaves) >= 1, "Expected at least one leaf chunk"

        # Verify parent is a 'document' unit type
        assert parents[0].unit_type == "document"

        # Verify leaf chunks reference a valid parent
        parent_ids = {c.id for c in parents}
        for leaf in leaves:
            assert leaf.parent_id in parent_ids


def test_full_pipeline_produces_embeddings_and_indexes(client):
    """Upload -> parse -> chunk -> embed -> index (stubs) -> verify all 7 stages complete."""
    from app.services.embedders.stub import StubEmbedder
    from app.services.indexers.stub import StubVectorIndexer, StubLexicalIndexer

    rich_artifact = ParsedArtifact(
        document_id=uuid4(),
        pages=[
            ParsedPage(
                page_number=1,
                text="First paragraph with enough text to exceed the minimum threshold.\n\n"
                     "Second paragraph also with sufficient length to be included as a chunk.",
                blocks=[],
            ),
            ParsedPage(
                page_number=2,
                text="Third paragraph on page two with adequate length for chunking.",
                blocks=[],
            ),
        ],
        tables=[],
        provenance=ParserProvenance(
            parser_backend="docling-local", parser_version="1.0.0", profile="local-cpu"
        ),
    )
    parser = DoclingDocumentParser(converter=lambda req: rich_artifact)
    embedder = StubEmbedder()
    vector_indexer = StubVectorIndexer()
    lexical_indexer = StubLexicalIndexer()

    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        embedder=embedder,
        vector_indexer=vector_indexer,
        lexical_indexer=lexical_indexer,
    )
    app.state._test_dispatcher = dispatcher

    response = client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": "Bearer test-token"},
        files={"file": ("embed-doc.txt", b"paragraph one\n\nparagraph two", "text/plain")},
        data={"title": "Embed Doc", "source_type": "loose_document"},
    )

    assert response.status_code == 201
    run_id = UUID(response.json()["ingestion_run_id"])

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
        assert len(stages) == 7
        assert all(s.status == "completed" for s in stages)

        # Verify embed stage produced embeddings
        embed_stage = next(s for s in stages if s.stage_name == "embed")
        assert embed_stage.details["embedding_count"] > 0

        # Verify index stages ran
        qdrant_stage = next(s for s in stages if s.stage_name == "index_qdrant")
        assert qdrant_stage.details["upserted_count"] > 0

        opensearch_stage = next(s for s in stages if s.stage_name == "index_opensearch")
        assert opensearch_stage.details["upserted_count"] > 0

    # Verify stubs tracked the upserts
    assert vector_indexer.upserted_count > 0
    assert lexical_indexer.upserted_count > 0


def test_pipeline_with_contextualizer_runs_eight_stages_and_augments(client):
    """ADR-0020: with a contextualizer injected the pipeline gains exactly one
    stage (contextualize, between chunk and embed), persists leaf prefixes,
    embeds the augmented search_text, and indexes augmented text alongside the
    original display_text."""
    from app.services.embedders.stub import StubEmbedder
    from app.services.indexers.opensearch_indexer import OpenSearchLexicalIndexer
    from app.services.indexers.stub import StubVectorIndexer
    from app.services.contextualizers.stub import StubChunkContextualizer
    from app.workflows.pipeline_runner import PipelineRunner

    class CapturingEmbedder(StubEmbedder):
        def __init__(self) -> None:
            super().__init__()
            self.seen_texts: list[str] = []

        def embed(self, *, chunk_ids, texts):
            self.seen_texts.extend(texts)
            return super().embed(chunk_ids=chunk_ids, texts=texts)

    rich_artifact = ParsedArtifact(
        document_id=uuid4(),
        pages=[
            ParsedPage(
                page_number=1,
                text="First paragraph with enough text to exceed the minimum threshold.\n\n"
                     "Second paragraph also with sufficient length to be included as a chunk.",
                blocks=[],
            ),
        ],
        tables=[],
        provenance=ParserProvenance(
            parser_backend="docling-local", parser_version="1.0.0", profile="local-cpu"
        ),
    )
    parser = DoclingDocumentParser(converter=lambda req: rich_artifact)
    embedder = CapturingEmbedder()
    lexical_indexer = OpenSearchLexicalIndexer(index_name="ctx_e2e", _mock=True)
    runner = PipelineRunner(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        embedder=embedder,
        vector_indexer=StubVectorIndexer(),
        lexical_indexer=lexical_indexer,
        contextualizer=StubChunkContextualizer(),
    )
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        runner=runner,
    )
    app.state._test_dispatcher = dispatcher

    response = client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": "Bearer test-token"},
        files={"file": ("ctx-doc.txt", b"paragraph one\n\nparagraph two", "text/plain")},
        data={"title": "Ctx Doc", "source_type": "loose_document"},
    )
    assert response.status_code == 201
    run_id = UUID(response.json()["ingestion_run_id"])

    dispatcher._execute_pipeline(run_id)

    expected_prefix = "[context: Ctx Doc]"
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
        assert [s.stage_name for s in stages] == [
            "parse",
            "persist_artifact",
            "chunk",
            "contextualize",
            "embed",
            "index_qdrant",
            "index_opensearch",
            "quality_report",
        ]
        assert all(s.status == "completed" for s in stages)

        ctx_stage = next(s for s in stages if s.stage_name == "contextualize")
        assert ctx_stage.details["contextualized_count"] > 0
        assert ctx_stage.details["rows_updated"] >= ctx_stage.details["contextualized_count"]

        chunks = list(
            session.scalars(
                select(ChunkModel).where(ChunkModel.document_id == run.document_id)
            ).all()
        )
        leaves = [c for c in chunks if c.parent_id is not None]
        parents = [c for c in chunks if c.parent_id is None]
        assert leaves and parents
        assert all(c.context_prefix == expected_prefix for c in leaves)
        assert all(c.context_prefix is None for c in parents)

    # Embedder received the augmented search_text, not the bare text.
    assert embedder.seen_texts
    assert all(t.startswith(f"{expected_prefix}\n") for t in embedder.seen_texts)

    # OpenSearch indexed augmented `text` and original `display_text`.
    sources = [d for d in lexical_indexer._last_bulk_body if "text" in d]
    assert sources
    for source in sources:
        assert source["text"].startswith(f"{expected_prefix}\n")
        assert not source["display_text"].startswith(expected_prefix)
        assert source["text"] == f"{expected_prefix}\n{source['display_text']}"
