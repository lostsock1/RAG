from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    SparseVector as QdrantSparseVector,
    VectorParams,
    SparseVectorParams,
    SparseIndexParams,
)

from app.schemas.chunks import Chunk
from app.schemas.embeddings import EmbeddingResult
from app.services.indexers.base import VectorIndexer
from app.services.retrieval.acl_filter import NO_EXPIRY_TS

logger = logging.getLogger(__name__)


def _expires_at_ts(expires_at: object) -> int:
    """Numeric expiry for the payload ACL filter (epoch seconds).

    ``NO_EXPIRY_TS`` sentinel when unset — the filter uses an unconditional
    ``Range(gt=now)``, so every point must carry a comparable number.
    """
    if expires_at is None:
        return NO_EXPIRY_TS
    if isinstance(expires_at, datetime):
        value = expires_at
    else:
        value = datetime.fromisoformat(str(expires_at))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp())

_DENSE_VECTOR_NAME = "dense"
_SPARSE_VECTOR_NAME = "sparse"
_DENSE_DIMENSION = 1024


class QdrantVectorIndexer:
    """Writes dense + sparse vectors with ACL metadata to Qdrant.

    In production, connects to a real Qdrant instance. For testing,
    pass ``_in_memory=True`` to use Qdrant's in-memory mode.
    """

    def __init__(
        self,
        collection_name: str = "uber_rag_chunks",
        host: str = "localhost",
        port: int = 6333,
        api_key: str | None = None,
        dense_dimension: int = _DENSE_DIMENSION,
        _in_memory: bool = False,
    ) -> None:
        self._collection_name = collection_name
        self._dense_dimension = dense_dimension
        self._client: QdrantClient | None = None
        self._host = host
        self._port = port
        self._api_key = api_key
        self._in_memory = _in_memory
        self._last_upserted_points: list[PointStruct] = []

    def _ensure_client(self) -> QdrantClient:
        if self._client is None:
            if self._in_memory:
                self._client = QdrantClient(":memory:")
            else:
                self._client = QdrantClient(host=self._host, port=self._port, api_key=self._api_key)
            self._ensure_collection()
        return self._client

    def _ensure_collection(self) -> None:
        client = self._client
        assert client is not None
        existing = [c.name for c in client.get_collections().collections]
        if self._collection_name not in existing:
            client.create_collection(
                collection_name=self._collection_name,
                vectors_config={
                    _DENSE_VECTOR_NAME: VectorParams(
                        size=self._dense_dimension,
                        distance=Distance.COSINE,
                    ),
                },
                sparse_vectors_config={
                    _SPARSE_VECTOR_NAME: SparseVectorParams(
                        index=SparseIndexParams(on_disk=False),
                    ),
                },
            )
            logger.info("Created Qdrant collection %s", self._collection_name)

    def upsert(
        self,
        *,
        chunks: list[Chunk],
        embeddings: list[EmbeddingResult],
        acl_metadata: dict,
    ) -> int:
        if not chunks:
            return 0

        client = self._ensure_client()

        points: list[PointStruct] = []
        for chunk, emb in zip(chunks, embeddings):
            if chunk.id is None:
                raise RuntimeError("Qdrant indexing requires persisted chunk IDs.")
            point_id = _deterministic_point_id(chunk.document_id, chunk.chunk_index)
            point = PointStruct(
                id=str(point_id),
                vector={
                    _DENSE_VECTOR_NAME: emb.dense.values,
                    _SPARSE_VECTOR_NAME: QdrantSparseVector(
                        indices=emb.sparse.indices,
                        values=emb.sparse.values,
                    ),
                },
                payload={
                    "document_id": str(chunk.document_id),
                    "chunk_id": str(chunk.id),
                    "chunk_index": chunk.chunk_index,
                    "unit_type": chunk.unit_type,
                    "heading_path": chunk.heading_path,
                    "text": chunk.text,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "tenant_id": acl_metadata.get("tenant_id", ""),
                    "owner_user_id": acl_metadata.get("owner_user_id", ""),
                    "allowed_user_ids": acl_metadata.get("allowed_user_ids", []),
                    "group_ids": acl_metadata.get("group_ids", []),
                    "allowed_group_ids": acl_metadata.get("allowed_group_ids", acl_metadata.get("group_ids", [])),
                    "visibility": acl_metadata.get("visibility", "private"),
                    "sensitivity": acl_metadata.get("sensitivity", "internal"),
                    "sensitivity_rank": acl_metadata.get("sensitivity_rank", 200),
                    "expires_at": acl_metadata.get("expires_at"),
                    "expires_at_ts": _expires_at_ts(acl_metadata.get("expires_at")),
                    "acl_policy_id": acl_metadata.get("acl_policy_id", ""),
                    "acl_policy_version": acl_metadata.get("acl_policy_version", 1),
                    "allowed_role_ids": acl_metadata.get("allowed_role_ids", []),
                    "allowed_org_unit_ids": acl_metadata.get("allowed_org_unit_ids", []),
                    "allowed_project_ids": acl_metadata.get("allowed_project_ids", []),
                },
            )
            points.append(point)

        client.upsert(collection_name=self._collection_name, points=points)
        self._last_upserted_points = points

        logger.info("Upserted %d points to Qdrant collection %s", len(points), self._collection_name)
        return len(points)


def _deterministic_point_id(document_id: UUID, chunk_index: int) -> UUID:
    """Deterministic UUID for a chunk's Qdrant point from (document_id, chunk_index)."""
    from uuid import uuid5

    _NS = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    return uuid5(_NS, f"qdrant:{document_id}:{chunk_index}")
