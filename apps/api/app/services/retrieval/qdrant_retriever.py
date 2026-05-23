from __future__ import annotations

from qdrant_client.models import FieldCondition, Filter, MatchAny, SparseVector

from app.services.retrieval.acl_filter import build_qdrant_acl_filter
from app.services.retrieval.base import QueryEmbedding, RetrievalHit, RetrievalQuery


class QdrantRetriever:
    def __init__(self, *, client: object, collection_name: str) -> None:
        self._client = client
        self._collection_name = collection_name

    def search_dense(self, query: RetrievalQuery, embedding: QueryEmbedding | list[float]) -> list[RetrievalHit]:
        vector = embedding.dense if isinstance(embedding, QueryEmbedding) else embedding
        response = self._client.query_points(
            collection_name=self._collection_name,
            query=vector,
            using="dense",
            limit=query.top_k,
            query_filter=_build_acl_filter(query),
            with_payload=True,
        )
        return _map_qdrant_hits(response)

    def search_sparse(self, query: RetrievalQuery, embedding: QueryEmbedding | dict | None = None, *, indices: list[int] | None = None, values: list[float] | None = None) -> list[RetrievalHit]:
        sparse_indices = indices or []
        sparse_values = values or []
        if isinstance(embedding, QueryEmbedding):
            sparse_indices = embedding.sparse_indices
            sparse_values = embedding.sparse_values
        elif isinstance(embedding, dict):
            sparse = embedding.get("sparse", {})
            sparse_indices = list(sparse.get("indices", []))
            sparse_values = list(sparse.get("values", []))

        response = self._client.query_points(
            collection_name=self._collection_name,
            query=SparseVector(indices=sparse_indices, values=sparse_values),
            using="sparse",
            limit=query.top_k,
            query_filter=_build_acl_filter(query),
            with_payload=True,
        )
        return _map_qdrant_hits(response)


def _build_acl_filter(query: RetrievalQuery) -> Filter:
    """Build a payload-side ACL filter from the query context.

    The ACL filter enforces tenant scoping, tombstone guard, expiry, and
    access-control predicates directly in Qdrant — no pre-fetched ID list
    required.  If ``allowed_document_ids`` is non-empty it is applied as an
    additional narrow filter on top (opt-in "search within these N docs").
    """
    acl = build_qdrant_acl_filter(
        tenant_id=query.tenant_id,
        user_id=query.user_id,
        group_ids=query.group_ids,
    )
    if not query.allowed_document_ids:
        return acl

    # Narrow to the caller-supplied document subset on top of ACL
    narrow = FieldCondition(
        key="document_id",
        match=MatchAny(any=query.allowed_document_ids),
    )
    return Filter(must=[acl, narrow])


def _map_qdrant_hits(response: object) -> list[RetrievalHit]:
    points = getattr(response, "points", response)
    return [_map_qdrant_hit(point) for point in points]


def _map_qdrant_hit(point: object) -> RetrievalHit:
    payload = getattr(point, "payload", {}) or {}
    document_id = str(payload["document_id"])
    chunk_id = payload.get("chunk_id")
    return RetrievalHit(
        document_id=document_id,
        chunk_id=chunk_id,
        score=float(getattr(point, "score", 0.0)),
        text=payload.get("text", ""),
        page_start=payload.get("page_start"),
        page_end=payload.get("page_end"),
        heading_path=payload.get("heading_path", []),
    )
