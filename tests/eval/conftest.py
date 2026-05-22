"""Shared pytest fixtures for eval harness — full ingestion pipeline."""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID, uuid4
from dataclasses import dataclass

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.core.request_context import RequestContext
from app.db.base import session_factory
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParserProvenance
from app.services.parsers.base import DocumentParser, ParseRequest
from app.services.storage import LocalFilesystemStorageAdapter
from app.workflows.dispatcher import InProcessDispatcher

CORPUS_DIR = Path(__file__).parent / "fixtures" / "sample_corpus"


@dataclass
class EvalStack:
    """Holds the fully wired eval stack."""
    chat_service: object  # ChatService
    context: RequestContext
    document_ids: list[UUID]
    tenant_id: UUID
    user_id: UUID


class _MarkdownParser(DocumentParser):
    """Simple parser that reads markdown files into ParsedArtifact."""

    backend_name = "eval-markdown"

    def parse(self, request: ParseRequest) -> ParsedArtifact:
        path = Path(request.local_source_path)
        text = path.read_text(encoding="utf-8")
        return ParsedArtifact(
            document_id=UUID(request.document_id),
            pages=[ParsedPage(page_number=1, text=text, blocks=[])],
            tables=[],
            provenance=ParserProvenance(
                parser_backend="docling-local",
                parser_version="1.0.0",
                profile="local-cpu",
            ),
        )


def _ingest_corpus_documents(
    *,
    dispatcher: InProcessDispatcher,
    storage: LocalFilesystemStorageAdapter,
    tenant_id: UUID,
    user_id: UUID,
) -> list[UUID]:
    """Ingest all markdown files from the corpus directory.

    Uses ``create_document_with_owner_acl`` so that ACL grants, policy
    snapshots, and sensitivity ranks are all properly set up — the same
    path the real upload endpoint uses.
    """
    from app.repositories.documents import create_document_with_owner_acl

    document_ids: list[UUID] = []
    for md_file in sorted(CORPUS_DIR.glob("*.md")):
        content = md_file.read_bytes()
        title = md_file.stem.replace("_", " ").title()

        # Use a placeholder object_key first; we'll fix it after we know the doc ID
        placeholder_key = f"{tenant_id}/placeholder/{md_file.name}"

        # Create document + ACL grant via the canonical repository helper
        doc = create_document_with_owner_acl(
            tenant_id=tenant_id,
            owner_user_id=user_id,
            title=title,
            source_type="loose_document",
            source_hash=f"eval-fixture-{md_file.stem}",
            file_name=md_file.name,
            file_size_bytes=len(content),
            object_key=placeholder_key,
        )
        doc_id = doc.id

        # Fix object_key to use the actual document ID
        object_key = f"{tenant_id}/{doc_id}/{md_file.name}"
        from sqlalchemy import update as sa_update
        from app.db.models.document import Document
        with session_factory() as session:
            session.execute(
                sa_update(Document)
                .where(Document.id == doc_id)
                .values(object_key=object_key)
            )
            session.commit()

        # Store file
        storage.put_object(object_key=object_key, content=content, content_type="text/markdown")

        # Create ingestion run
        from app.repositories.ingestion import create_ingestion_run
        run = create_ingestion_run(
            document_id=doc_id,
            tenant_id=tenant_id,
            parser_backend="docling-local",
            source_hash=f"eval-fixture-{md_file.stem}",
        )

        # Run pipeline synchronously
        dispatcher._execute_pipeline(run.id)
        document_ids.append(doc_id)

    return document_ids


@pytest.fixture(scope="session")
def eval_stack():
    """Session-scoped fixture: full ingestion pipeline with real BGE-M3 + Qdrant in-memory."""
    from app.services.answer_verifier import AnswerVerifier
    from app.services.chat_service import ChatService
    from app.services.citation_resolver import CitationResolver
    from app.services.context_builder import DefaultContextBuilder
    from app.services.embedders.bge_m3 import BgeM3Embedder
    from app.services.indexers.qdrant_indexer import QdrantVectorIndexer
    from app.services.indexers.opensearch_indexer import OpenSearchLexicalIndexer
    from app.services.retrieval.hybrid_retriever import HybridSearchRetriever
    from app.services.retrieval.qdrant_retriever import QdrantRetriever
    from app.services.retrieval.router import QueryRouter
    from app.services.retrieval.search_service import SearchService
    from app.services.retrieval.query_embedder import BgeM3QueryEmbedder
    from app.services.retrieval.reranker import StubReranker
    from app.services.llm_backend import StubLlmBackend
    from tempfile import TemporaryDirectory

    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    user_id = UUID("00000000-0000-0000-0000-000000000002")

    with TemporaryDirectory() as tmp_dir:
        # 1. SQLite DB with Alembic migrations
        db_path = Path(tmp_dir) / "eval.db"
        database_url = f"sqlite:///{db_path}"
        engine = create_engine(database_url)

        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        # Create tenant and user
        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Eval Tenant", slug="eval"))
            session.add(User(
                id=user_id,
                tenant_id=tenant_id,
                email="eval@test.com",
                display_name="Eval User",
                roles=["editor"],
            ))
            session.commit()

        # 2. Storage
        storage_dir = Path(tmp_dir) / "storage"
        storage = LocalFilesystemStorageAdapter(root_dir=storage_dir)

        # 3. Real BGE-M3 embedder (loads model once)
        embedder = BgeM3Embedder()

        # 4. Qdrant in-memory
        qdrant_indexer = QdrantVectorIndexer(
            collection_name="eval_chunks",
            _in_memory=True,
        )

        # 5. OpenSearch mock
        opensearch_indexer = OpenSearchLexicalIndexer(
            index_name="eval_chunks",
            _mock=True,
        )

        # 6. Parser + Dispatcher
        parser = _MarkdownParser()
        dispatcher = InProcessDispatcher(
            parser=parser,
            parser_backend="docling-local",
            parser_profile="local-cpu",
            storage=storage,
            embedder=embedder,
            vector_indexer=qdrant_indexer,
            lexical_indexer=opensearch_indexer,
        )

        # 7. Ingest corpus
        document_ids = _ingest_corpus_documents(
            dispatcher=dispatcher,
            storage=storage,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        # 8. Build search stack
        qdrant_client = qdrant_indexer._ensure_client()
        qdrant_retriever = QdrantRetriever(
            client=qdrant_client,
            collection_name="eval_chunks",
        )

        # OpenSearch retriever: stub that returns empty results (dense-only eval)
        opensearch_retriever = _StubOpenSearchRetriever()

        # Share the already-loaded BGE-M3 model with the query embedder
        query_embedder = BgeM3QueryEmbedder(embedder=embedder)

        retriever = HybridSearchRetriever(
            router=QueryRouter(),
            lexical_retriever=opensearch_retriever,
            vector_retriever=qdrant_retriever,
            query_embedder=query_embedder,
            search_sources_repository=_EvalSearchSourcesRepo(),
            reranker=StubReranker(),
            rerank_candidate_limit=20,
        )

        search_service = SearchService(retriever=retriever)

        # 9. Build ChatService with StubLlmBackend
        chat_service = ChatService(
            search_service=search_service,
            context_builder=DefaultContextBuilder(),
            llm_backend=StubLlmBackend(),
            citation_resolver=CitationResolver(),
            answer_verifier=AnswerVerifier(),
            max_context_characters=4000,
            max_context_blocks=None,
        )

        context = RequestContext(
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            group_ids=["eval-group"],
            roles=["eval"],
            scopes=["documents:read"],
        )

        yield EvalStack(
            chat_service=chat_service,
            context=context,
            document_ids=document_ids,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        # Cleanup
        session_factory.configure(bind=None)
        engine.dispose()


class _StubOpenSearchRetriever:
    """Returns empty results — we rely on dense retrieval only for eval."""

    def search(self, query):
        return []


class _EvalSearchSourcesRepo:
    """Stub — parent-child expansion isn't critical for faithfulness measurement."""

    def get_parent_chunks_by_child_ids(self, *, child_chunk_ids):
        return {}
