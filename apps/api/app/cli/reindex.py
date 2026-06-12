"""Reindex CLI (master plan E4a): stream chunks from Postgres → re-embed →
re-upsert Qdrant + OpenSearch with the document's CURRENT ACL payload.

Postgres chunk rows are the canonical source: each document's leaf chunks are
re-embedded over ``search_text`` (so a persisted ADR-0020 ``context_prefix``
is honored) and re-upserted with ``get_document_index_acl_metadata`` — the
ACL payload as it is NOW (policy id/version, sensitivity rank, expiry), not
the snapshot stamped at ingest time. Deterministic point/doc ids make
re-upserts idempotent; documents stream in stable id order so an interrupted
run resumes with ``--after-document-id`` set to the last completed id from
the log.

Truthful failure, no silent fallback: a missing database bind, a document id
outside the tenant, or a document without an ACL grant aborts the run; the
entrypoint never substitutes stub components.

Usage:
    python -m app.cli.reindex --tenant-id <uuid>
        [--document-id <uuid> ...] [--after-document-id <uuid>]
        [--database-url <url>]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.base import make_engine, session_factory
from app.db.models.document import Document
from app.repositories.chunks import get_chunks_as_schemas
from app.repositories.documents import get_document_index_acl_metadata
from app.services.embedders.base import Embedder
from app.services.indexers.base import LexicalIndexer, VectorIndexer
from app.services.indexers.opensearch_indexer import OpenSearchLexicalIndexer
from app.services.indexers.qdrant_indexer import QdrantVectorIndexer

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReindexReport:
    tenant_id: str
    documents_seen: int = 0
    documents_reindexed: int = 0
    documents_skipped_no_leaves: int = 0
    leaves_embedded: int = 0
    qdrant_upserted: int = 0
    opensearch_upserted: int = 0
    last_document_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _select_document_ids(
    *,
    tenant_id: UUID,
    document_ids: list[UUID] | None,
    after_document_id: UUID | None,
) -> list[UUID]:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Reindex is not configured: session_factory has no database bind."
            )
        statement = (
            select(Document.id)
            .where(
                Document.tenant_id == tenant_id,
                Document.is_tombstoned == False,  # noqa: E712
            )
            .order_by(Document.id.asc())
        )
        if after_document_id is not None:
            statement = statement.where(Document.id > after_document_id)
        selected = list(session.scalars(statement))

    if document_ids is None:
        return selected

    requested = set(document_ids)
    missing = requested - set(selected)
    if missing:
        raise RuntimeError(
            "Documents do not belong to tenant "
            f"{tenant_id} (or are tombstoned/behind the resume cursor): "
            f"{sorted(str(value) for value in missing)}"
        )
    return [doc_id for doc_id in selected if doc_id in requested]


def reindex_document(
    *,
    document_id: UUID,
    embedder: Embedder,
    vector_indexer: VectorIndexer,
    lexical_indexer: LexicalIndexer,
) -> tuple[int, int, int]:
    """Re-embed and re-upsert one document. Returns (leaves, qdrant, opensearch)."""
    chunks = get_chunks_as_schemas(document_id=document_id)
    leaf_chunks = [c for c in chunks if c.parent_id is not None]
    if not leaf_chunks:
        return (0, 0, 0)

    chunk_ids = []
    for chunk in leaf_chunks:
        if chunk.id is None:
            raise RuntimeError(
                f"Reindex requires persisted chunk IDs (document {document_id})."
            )
        chunk_ids.append(chunk.id)
    embeddings = embedder.embed(
        chunk_ids=chunk_ids, texts=[c.search_text for c in leaf_chunks]
    )

    acl_metadata = get_document_index_acl_metadata(document_id=document_id)
    qdrant_count = vector_indexer.upsert(
        chunks=leaf_chunks, embeddings=embeddings, acl_metadata=acl_metadata
    )
    opensearch_count = lexical_indexer.upsert(
        chunks=leaf_chunks, acl_metadata=acl_metadata
    )
    return (len(leaf_chunks), qdrant_count, opensearch_count)


def reindex_tenant(
    *,
    tenant_id: UUID,
    embedder: Embedder,
    vector_indexer: VectorIndexer,
    lexical_indexer: LexicalIndexer,
    document_ids: list[UUID] | None = None,
    after_document_id: UUID | None = None,
) -> ReindexReport:
    report = ReindexReport(tenant_id=str(tenant_id))
    selected = _select_document_ids(
        tenant_id=tenant_id,
        document_ids=document_ids,
        after_document_id=after_document_id,
    )
    for document_id in selected:
        report.documents_seen += 1
        leaves, qdrant_count, opensearch_count = reindex_document(
            document_id=document_id,
            embedder=embedder,
            vector_indexer=vector_indexer,
            lexical_indexer=lexical_indexer,
        )
        if leaves == 0:
            report.documents_skipped_no_leaves += 1
            logger.info("Reindex skipped document %s: no leaf chunks.", document_id)
        else:
            report.documents_reindexed += 1
            report.leaves_embedded += leaves
            report.qdrant_upserted += qdrant_count
            report.opensearch_upserted += opensearch_count
            logger.info(
                "Reindexed document %s: %d leaves (qdrant=%d, opensearch=%d).",
                document_id,
                leaves,
                qdrant_count,
                opensearch_count,
            )
        # Resume boundary: this document is fully re-upserted.
        report.last_document_id = str(document_id)
    return report


def build_embedder() -> Embedder:
    """ADR-0013 frozen default. Imported lazily: the model loads on first use."""
    from app.services.embedders.bge_m3 import BgeM3Embedder

    return BgeM3Embedder()


def build_vector_indexer(settings: Settings) -> QdrantVectorIndexer:
    return QdrantVectorIndexer(
        collection_name=settings.qdrant_collection_name,
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        api_key=settings.qdrant_api_key,
    )


def build_lexical_indexer(settings: Settings) -> OpenSearchLexicalIndexer:
    auth = None
    if settings.opensearch_username and settings.opensearch_password:
        auth = (settings.opensearch_username, settings.opensearch_password)
    return OpenSearchLexicalIndexer(
        index_name=settings.opensearch_index_name,
        host=settings.opensearch_host,
        port=settings.opensearch_port,
        auth=auth,
        use_ssl=settings.opensearch_use_ssl,
        verify_certs=settings.opensearch_verify_certs,
    )


def main(
    argv: list[str] | None = None,
    *,
    settings_factory=get_settings,
    embedder_factory=build_embedder,
    vector_indexer_factory=build_vector_indexer,
    lexical_indexer_factory=build_lexical_indexer,
) -> int:
    parser = argparse.ArgumentParser(
        prog="reindex",
        description=(
            "Stream a tenant's chunks from Postgres, re-embed, and re-upsert "
            "Qdrant + OpenSearch with the current ACL payload."
        ),
    )
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument(
        "--document-id",
        type=UUID,
        action="append",
        dest="document_ids",
        help="Restrict to specific documents (repeatable).",
    )
    parser.add_argument(
        "--after-document-id",
        type=UUID,
        help="Resume cursor: skip documents up to and including this id.",
    )
    parser.add_argument(
        "--database-url",
        help="Override settings.database_url for this run.",
    )
    args = parser.parse_args(argv)

    settings = settings_factory()
    database_url = args.database_url or settings.database_url
    if not database_url:
        print(
            "Reindex requires a database: pass --database-url or set DATABASE_URL.",
            file=sys.stderr,
        )
        return 2

    previous_bind = session_factory.kw.get("bind")
    engine = make_engine(database_url)
    session_factory.configure(bind=engine)
    try:
        report = reindex_tenant(
            tenant_id=args.tenant_id,
            embedder=embedder_factory(),
            vector_indexer=vector_indexer_factory(settings),
            lexical_indexer=lexical_indexer_factory(settings),
            document_ids=args.document_ids,
            after_document_id=args.after_document_id,
        )
    finally:
        session_factory.configure(bind=previous_bind)
        engine.dispose()

    print(json.dumps(report.to_dict(), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
