"""Reindex CLI (master plan E4a): stream chunks from Postgres → re-embed →
re-upsert Qdrant + OpenSearch with the document's CURRENT ACL payload.

Acceptance (frozen in the master plan): round-trip test — ingest, then
reindex into fresh indexes, and retrieval results are identical. Plus:
per-tenant scoping, resume cursor, tombstone/no-leaf skips, leaf-only
embedding over ``search_text``, idempotent re-runs (deterministic ids), and
ACL freshness (a grant change after ingest reaches the reindexed payload
without re-ingesting).
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, update as sa_update

from app.db.acl_models import AclAllowedUser, AclGrant
from app.db.base import session_factory
from app.db.models.chunk import Chunk as ChunkModel
from app.db.models.document import Document
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParserProvenance
from app.services.embedders.stub import StubEmbedder
from app.services.indexers.opensearch_indexer import OpenSearchLexicalIndexer
from app.services.indexers.qdrant_indexer import QdrantVectorIndexer
from app.services.parsers.base import DocumentParser, ParseRequest
from app.services.storage import LocalFilesystemStorageAdapter
from app.workflows.dispatcher import InProcessDispatcher

TENANT_ONE = UUID("00000000-0000-0000-0000-0000000000a1")
TENANT_TWO = UUID("00000000-0000-0000-0000-0000000000a2")
USER_ONE = UUID("00000000-0000-0000-0000-0000000000b1")
USER_TWO = UUID("00000000-0000-0000-0000-0000000000b2")

_DOCS = {
    "alpha": (
        "# Alpha manual\n\n"
        "The alpha subsystem regulates pressure across the primary manifold. "
        "Operators must verify the relief valve before each start cycle.\n\n"
        "Maintenance intervals for the alpha subsystem are ninety days. "
        "Each interval requires a full seal inspection and lubricant change.\n\n"
        "Decommissioning the alpha subsystem requires a two-person sign-off "
        "and a pressure bleed lasting thirty minutes."
    ),
    "bravo": (
        "# Bravo handbook\n\n"
        "Bravo units ship with a sealed coolant loop rated for five years. "
        "The loop must never be opened outside a certified facility.\n\n"
        "Bravo diagnostics run nightly and write a summary ledger entry. "
        "A missed ledger entry indicates a failed diagnostic cycle."
    ),
    "charlie": (
        "# Charlie notes\n\n"
        "Charlie stations synchronize clocks against the site reference "
        "every six hours, drifting no more than two milliseconds.\n\n"
        "Charlie operators rotate weekly and record handover notes in the "
        "station logbook before ending a shift."
    ),
}

_TENANT_TWO_DOC = (
    "# Delta digest\n\n"
    "Delta belongs to a different tenant and must never appear in tenant "
    "one's reindex stream, counts, or upserted payloads."
)


class _MarkdownParser(DocumentParser):
    backend_name = "test-markdown"

    def parse(self, request: ParseRequest) -> ParsedArtifact:
        text = Path(request.local_source_path).read_text(encoding="utf-8")
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


class _RecordingLexicalIndexer:
    """Wraps the real mock-mode OpenSearch indexer and snapshots every bulk
    body, so ingest-time and reindex-time index payloads can be compared."""

    def __init__(self, inner: OpenSearchLexicalIndexer) -> None:
        self.inner = inner
        self.bulks: list[list[dict]] = []

    def upsert(self, *, chunks, acl_metadata) -> int:
        count = self.inner.upsert(chunks=chunks, acl_metadata=acl_metadata)
        self.bulks.append([dict(item) for item in self.inner._last_bulk_body])
        return count


class _RecordingEmbedder:
    def __init__(self) -> None:
        self.inner = StubEmbedder()
        self.calls: list[list[str]] = []

    def embed(self, *, chunk_ids, texts):
        self.calls.append(list(texts))
        return self.inner.embed(chunk_ids=chunk_ids, texts=texts)


class _RecordingVectorIndexer:
    def __init__(self) -> None:
        self.document_ids: list[str] = []
        self.acl_payloads: list[dict] = []

    def upsert(self, *, chunks, embeddings, acl_metadata) -> int:
        self.document_ids.extend(sorted({str(c.document_id) for c in chunks}))
        self.acl_payloads.append(dict(acl_metadata))
        return len(chunks)


class _NullLexicalIndexer:
    def upsert(self, *, chunks, acl_metadata) -> int:
        return len(chunks)


class _ReindexEnv:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


def _ingest_document(*, dispatcher, storage, tenant_id, user_id, slug, content) -> UUID:
    from app.repositories.documents import create_document_with_owner_acl
    from app.repositories.ingestion import create_ingestion_run

    raw = content.encode("utf-8")
    doc = create_document_with_owner_acl(
        tenant_id=tenant_id,
        owner_user_id=user_id,
        title=slug.title(),
        source_type="loose_document",
        source_hash=f"reindex-fixture-{slug}",
        file_name=f"{slug}.md",
        file_size_bytes=len(raw),
        object_key=f"{tenant_id}/placeholder/{slug}.md",
    )
    object_key = f"{tenant_id}/{doc.id}/{slug}.md"
    with session_factory() as session:
        session.execute(
            sa_update(Document).where(Document.id == doc.id).values(object_key=object_key)
        )
        session.commit()
    storage.put_object(object_key=object_key, content=raw, content_type="text/markdown")
    run = create_ingestion_run(
        document_id=doc.id,
        tenant_id=tenant_id,
        parser_backend="docling-local",
        source_hash=f"reindex-fixture-{slug}",
    )
    dispatcher._execute_pipeline(run.id)
    return doc.id


@pytest.fixture(scope="module")
def env():
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'reindex.db'}"
        engine = create_engine(database_url)
        config = Config(str(Path("infra/migrations/alembic.ini")))
        config.set_main_option("sqlalchemy.url", database_url)
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=TENANT_ONE, name="Tenant One", slug="t1"))
            session.add(Tenant(id=TENANT_TWO, name="Tenant Two", slug="t2"))
            session.add(
                User(
                    id=USER_ONE,
                    tenant_id=TENANT_ONE,
                    email="one@t1.com",
                    display_name="One",
                    roles=["editor"],
                )
            )
            session.add(
                User(
                    id=USER_TWO,
                    tenant_id=TENANT_TWO,
                    email="two@t2.com",
                    display_name="Two",
                    roles=["editor"],
                )
            )
            session.commit()

        storage = LocalFilesystemStorageAdapter(root_dir=Path(tmp_dir) / "storage")
        embedder = StubEmbedder()
        ingest_vector_indexer = QdrantVectorIndexer(
            collection_name="ingest_chunks", dense_dimension=8, _in_memory=True
        )
        ingest_lexical_indexer = _RecordingLexicalIndexer(
            OpenSearchLexicalIndexer(index_name="ingest_chunks", _mock=True)
        )
        dispatcher = InProcessDispatcher(
            parser=_MarkdownParser(),
            parser_backend="docling-local",
            parser_profile="local-cpu",
            storage=storage,
            embedder=embedder,
            vector_indexer=ingest_vector_indexer,
            lexical_indexer=ingest_lexical_indexer,
        )

        document_ids: dict[str, UUID] = {}
        for slug, content in _DOCS.items():
            document_ids[slug] = _ingest_document(
                dispatcher=dispatcher,
                storage=storage,
                tenant_id=TENANT_ONE,
                user_id=USER_ONE,
                slug=slug,
                content=content,
            )
        delta_id = _ingest_document(
            dispatcher=dispatcher,
            storage=storage,
            tenant_id=TENANT_TWO,
            user_id=USER_TWO,
            slug="delta",
            content=_TENANT_TWO_DOC,
        )

        with session_factory() as session:
            leaf_counts = {
                slug: session.scalars(
                    select(ChunkModel.id).where(
                        ChunkModel.document_id == doc_id,
                        ChunkModel.parent_id.is_not(None),
                    )
                ).all()
                for slug, doc_id in document_ids.items()
            }
        assert all(leaf_counts.values()), "every fixture doc must produce leaf chunks"

        yield _ReindexEnv(
            engine=engine,
            embedder=embedder,
            document_ids=document_ids,
            delta_id=delta_id,
            leaf_counts={slug: len(ids) for slug, ids in leaf_counts.items()},
            ingest_vector_indexer=ingest_vector_indexer,
            ingest_lexical_indexer=ingest_lexical_indexer,
        )

        session_factory.configure(bind=None)
        engine.dispose()


def _tenant_one_ordered_ids(env) -> list[UUID]:
    return sorted(env.document_ids.values(), key=str)


def test_reindex_requires_database_bind(env):
    from app.cli.reindex import reindex_tenant

    session_factory.configure(bind=None)
    try:
        with pytest.raises(RuntimeError, match="database bind"):
            reindex_tenant(
                tenant_id=TENANT_ONE,
                embedder=StubEmbedder(),
                vector_indexer=_RecordingVectorIndexer(),
                lexical_indexer=_NullLexicalIndexer(),
            )
    finally:
        session_factory.configure(bind=env.engine)


def test_reindex_streams_only_target_tenant_in_stable_order(env):
    from app.cli.reindex import reindex_tenant

    vector = _RecordingVectorIndexer()
    report = reindex_tenant(
        tenant_id=TENANT_ONE,
        embedder=StubEmbedder(),
        vector_indexer=vector,
        lexical_indexer=_NullLexicalIndexer(),
    )

    expected_ids = [str(doc_id) for doc_id in _tenant_one_ordered_ids(env)]
    assert vector.document_ids == expected_ids  # stable id order, no tenant-two doc
    assert str(env.delta_id) not in vector.document_ids
    assert report.documents_seen == 3
    assert report.documents_reindexed == 3
    assert report.leaves_embedded == sum(env.leaf_counts.values())
    assert report.qdrant_upserted == report.leaves_embedded
    assert report.opensearch_upserted == report.leaves_embedded
    assert report.last_document_id == expected_ids[-1]


def test_reindex_document_ids_filter(env):
    from app.cli.reindex import reindex_tenant

    target = env.document_ids["bravo"]
    vector = _RecordingVectorIndexer()
    report = reindex_tenant(
        tenant_id=TENANT_ONE,
        embedder=StubEmbedder(),
        vector_indexer=vector,
        lexical_indexer=_NullLexicalIndexer(),
        document_ids=[target],
    )
    assert vector.document_ids == [str(target)]
    assert report.documents_seen == 1
    assert report.leaves_embedded == env.leaf_counts["bravo"]


def test_reindex_document_ids_outside_tenant_are_refused(env):
    from app.cli.reindex import reindex_tenant

    with pytest.raises(RuntimeError, match="tenant"):
        reindex_tenant(
            tenant_id=TENANT_ONE,
            embedder=StubEmbedder(),
            vector_indexer=_RecordingVectorIndexer(),
            lexical_indexer=_NullLexicalIndexer(),
            document_ids=[env.delta_id],
        )


def test_reindex_resumes_after_document_cursor(env):
    from app.cli.reindex import reindex_tenant

    ordered = _tenant_one_ordered_ids(env)
    vector = _RecordingVectorIndexer()
    report = reindex_tenant(
        tenant_id=TENANT_ONE,
        embedder=StubEmbedder(),
        vector_indexer=vector,
        lexical_indexer=_NullLexicalIndexer(),
        after_document_id=ordered[0],
    )
    assert vector.document_ids == [str(doc_id) for doc_id in ordered[1:]]
    assert report.documents_seen == 2


def test_reindex_skips_tombstoned_documents(env):
    from app.cli.reindex import reindex_tenant

    tombstoned = env.document_ids["alpha"]
    with session_factory() as session:
        session.execute(
            sa_update(Document).where(Document.id == tombstoned).values(is_tombstoned=True)
        )
        session.commit()
    try:
        vector = _RecordingVectorIndexer()
        report = reindex_tenant(
            tenant_id=TENANT_ONE,
            embedder=StubEmbedder(),
            vector_indexer=vector,
            lexical_indexer=_NullLexicalIndexer(),
        )
        assert str(tombstoned) not in vector.document_ids
        assert report.documents_seen == 2
    finally:
        with session_factory() as session:
            session.execute(
                sa_update(Document)
                .where(Document.id == tombstoned)
                .values(is_tombstoned=False)
            )
            session.commit()


def test_reindex_embeds_only_leaf_search_text(env):
    from app.cli.reindex import reindex_tenant
    from app.repositories.chunks import get_chunks_as_schemas, set_chunk_context_prefixes

    target = env.document_ids["charlie"]
    chunks = get_chunks_as_schemas(document_id=target)
    leaves = [c for c in chunks if c.parent_id is not None]
    parents = [c for c in chunks if c.parent_id is None]
    prefixed_leaf = leaves[0]
    set_chunk_context_prefixes(prefixes={prefixed_leaf.id: "Charlie notes > Synchronization"})
    try:
        embedder = _RecordingEmbedder()
        reindex_tenant(
            tenant_id=TENANT_ONE,
            embedder=embedder,
            vector_indexer=_RecordingVectorIndexer(),
            lexical_indexer=_NullLexicalIndexer(),
            document_ids=[target],
        )
        assert len(embedder.calls) == 1
        texts = embedder.calls[0]
        assert len(texts) == len(leaves)  # leaf-only embedding
        assert f"Charlie notes > Synchronization\n{prefixed_leaf.text}" in texts
        for parent in parents:
            assert parent.text not in texts
    finally:
        set_chunk_context_prefixes(prefixes={prefixed_leaf.id: None})


def _search_ranked(client, collection_name: str, queries: list[str]) -> dict[str, list[tuple]]:
    from app.services.retrieval.base import RetrievalQuery
    from app.services.retrieval.qdrant_retriever import QdrantRetriever
    from app.services.retrieval.query_embedder import BgeM3QueryEmbedder

    retriever = QdrantRetriever(client=client, collection_name=collection_name)
    query_embedder = BgeM3QueryEmbedder(embedder=StubEmbedder())
    out: dict[str, list[tuple]] = {}
    for query in queries:
        embedding = query_embedder.embed_query(query)
        retrieval_query = RetrievalQuery(
            query=query,
            tenant_id=str(TENANT_ONE),
            allowed_document_ids=[],
            top_k=10,
            user_id=str(USER_ONE),
            group_ids=[],
        )
        hits = retriever.search_dense(retrieval_query, embedding)
        out[query] = [(hit.chunk_id, round(hit.score, 6)) for hit in hits]
    return out


_ROUND_TRIP_QUERIES = [
    "alpha subsystem maintenance interval",
    "bravo coolant loop rating",
    "charlie clock synchronization drift",
]


def test_round_trip_reindex_yields_identical_retrieval(env):
    """Master-plan acceptance: ingest → reindex → identical retrieval results."""
    from app.cli.reindex import reindex_tenant

    before = _search_ranked(
        env.ingest_vector_indexer._ensure_client(), "ingest_chunks", _ROUND_TRIP_QUERIES
    )
    assert any(results for results in before.values()), "ingest index must serve hits"

    reindex_vector = QdrantVectorIndexer(
        collection_name="reindex_chunks", dense_dimension=8, _in_memory=True
    )
    reindex_lexical = _RecordingLexicalIndexer(
        OpenSearchLexicalIndexer(index_name="reindex_chunks", _mock=True)
    )
    report = reindex_tenant(
        tenant_id=TENANT_ONE,
        embedder=StubEmbedder(),
        vector_indexer=reindex_vector,
        lexical_indexer=reindex_lexical,
    )
    assert report.documents_reindexed == 3

    after = _search_ranked(
        reindex_vector._ensure_client(), "reindex_chunks", _ROUND_TRIP_QUERIES
    )
    assert after == before  # identical ranked ids AND scores

    # Lexical side: reindex produced the same per-chunk index documents the
    # original ingest produced (id-keyed _source equality).
    def _by_id(bulks: list[list[dict]]) -> dict[str, dict]:
        merged: dict[str, dict] = {}
        for bulk in bulks:
            for item in bulk:
                if str(item.get("_source", {}).get("tenant_id")) != str(TENANT_ONE):
                    continue
                merged[item["_id"]] = item["_source"]
        return merged

    assert _by_id(reindex_lexical.bulks) == _by_id(env.ingest_lexical_indexer.bulks)

    # Idempotency: a second reindex into the SAME collection changes nothing.
    second = reindex_tenant(
        tenant_id=TENANT_ONE,
        embedder=StubEmbedder(),
        vector_indexer=reindex_vector,
        lexical_indexer=reindex_lexical,
    )
    assert second.qdrant_upserted == report.qdrant_upserted
    again = _search_ranked(
        reindex_vector._ensure_client(), "reindex_chunks", _ROUND_TRIP_QUERIES
    )
    assert again == before


def test_reindex_carries_current_acl_payload_not_ingest_time_snapshot(env):
    """The CLI's reason to exist: ACL changes AFTER ingest must reach the
    re-upserted payload without re-ingesting the document."""
    from app.cli.reindex import reindex_tenant

    target = env.document_ids["alpha"]
    with session_factory() as session:
        grant = session.scalar(select(AclGrant).where(AclGrant.document_id == target))
        assert grant is not None
        session.add(AclAllowedUser(acl_grant_id=grant.id, user_id=USER_TWO))
        session.commit()

    vector = _RecordingVectorIndexer()
    reindex_tenant(
        tenant_id=TENANT_ONE,
        embedder=StubEmbedder(),
        vector_indexer=vector,
        lexical_indexer=_NullLexicalIndexer(),
        document_ids=[target],
    )
    assert len(vector.acl_payloads) == 1
    assert str(USER_TWO) in vector.acl_payloads[0]["allowed_user_ids"]

    # Ingest-time payload in the live index predates the grant change.
    client = env.ingest_vector_indexer._ensure_client()
    points, _ = client.scroll(
        collection_name="ingest_chunks", limit=200, with_payload=True
    )
    stale = [p.payload for p in points if p.payload["document_id"] == str(target)]
    assert stale and all(
        str(USER_TWO) not in p["allowed_user_ids"] for p in stale
    )


def test_builders_map_settings_to_real_components():
    from app.cli.reindex import build_lexical_indexer, build_vector_indexer
    from app.core.config import Settings

    settings = Settings(
        qdrant_host="vector.internal",
        qdrant_port=7333,
        qdrant_api_key="qk",
        qdrant_collection_name="prod_chunks",
        opensearch_host="lexical.internal",
        opensearch_port=9201,
        opensearch_username="os-user",
        opensearch_password="os-pass",
        opensearch_use_ssl=True,
        opensearch_verify_certs=False,
        opensearch_index_name="prod_chunks",
    )

    vector = build_vector_indexer(settings)
    assert isinstance(vector, QdrantVectorIndexer)
    assert vector._collection_name == "prod_chunks"
    assert vector._host == "vector.internal"
    assert vector._port == 7333
    assert vector._api_key == "qk"

    lexical = build_lexical_indexer(settings)
    assert isinstance(lexical, OpenSearchLexicalIndexer)
    assert lexical._index_name == "prod_chunks"
    assert lexical._host == "lexical.internal"
    assert lexical._port == 9201
    assert lexical._auth == ("os-user", "os-pass")
    assert lexical._use_ssl is True
    assert lexical._verify_certs is False

    no_auth = build_lexical_indexer(Settings())
    assert no_auth._auth is None


def test_main_requires_database_url(env):
    from app.cli.reindex import main

    exit_code = main(
        ["--tenant-id", str(TENANT_ONE)],
        settings_factory=lambda: __import__("app.core.config", fromlist=["Settings"]).Settings(
            database_url=""
        ),
    )
    assert exit_code == 2


def test_main_runs_reindex_and_prints_report(env, capsys):
    """The entrypoint binds the DB, runs the tenant reindex with injected
    component factories (tests must not build real BGE-M3/Qdrant), prints a
    JSON report, and restores the previous session bind."""
    from app.cli.reindex import main

    database_url = str(env.engine.url)
    exit_code = main(
        [
            "--tenant-id",
            str(TENANT_ONE),
            "--database-url",
            database_url,
        ],
        embedder_factory=StubEmbedder,
        vector_indexer_factory=lambda settings: _RecordingVectorIndexer(),
        lexical_indexer_factory=lambda settings: _NullLexicalIndexer(),
    )
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tenant_id"] == str(TENANT_ONE)
    assert report["documents_reindexed"] == 3
    assert report["leaves_embedded"] == sum(env.leaf_counts.values())

    # main() must leave the module fixture's bind restored for later tests.
    with session_factory() as session:
        assert session.bind is not None
