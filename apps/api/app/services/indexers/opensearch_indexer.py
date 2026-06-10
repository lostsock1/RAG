from __future__ import annotations

import logging
from uuid import UUID

from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk

from app.schemas.chunks import Chunk
from app.services.indexers.base import LexicalIndexer

logger = logging.getLogger(__name__)


class OpenSearchLexicalIndexer:
    """Writes text chunks with ACL metadata to OpenSearch for BM25/phrase search.

    In production, connects to a real OpenSearch cluster. For testing,
    pass ``_mock=True`` to skip actual OpenSearch calls and capture the
    bulk body for assertions.
    """

    def __init__(
        self,
        index_name: str = "uber_rag_chunks",
        host: str = "localhost",
        port: int = 9200,
        auth: tuple[str, str] | None = None,
        use_ssl: bool = False,
        verify_certs: bool = True,
        _mock: bool = False,
    ) -> None:
        self._index_name = index_name
        self._host = host
        self._port = port
        self._auth = auth
        self._use_ssl = use_ssl
        self._verify_certs = verify_certs
        self._mock = _mock
        self._client: OpenSearch | None = None
        self._last_bulk_body: list[dict] = []

    def _ensure_client(self) -> OpenSearch:
        if self._client is None:
            client_kwargs: dict = {
                "hosts": [{"host": self._host, "port": self._port}],
                "http_auth": self._auth,
                "use_ssl": self._use_ssl,
                "verify_certs": self._verify_certs,
            }
            # Mirror the search runtime: suppress urllib3 warnings only when
            # verification is explicitly disabled (insecure local/dev override).
            if not self._verify_certs:
                client_kwargs["ssl_show_warn"] = False
            self._client = OpenSearch(**client_kwargs)
            self._ensure_index()
        return self._client

    def _ensure_index(self) -> None:
        client = self._client
        assert client is not None
        if not client.indices.exists(index=self._index_name):
            client.indices.create(
                index=self._index_name,
                body={
                    "mappings": {
                        "properties": {
                            "document_id": {"type": "keyword"},
                            "chunk_index": {"type": "integer"},
                            "unit_type": {"type": "keyword"},
                            "heading_path": {"type": "keyword"},
                            "text": {"type": "text", "analyzer": "standard"},
                            "page_start": {"type": "integer"},
                            "page_end": {"type": "integer"},
                            "tenant_id": {"type": "keyword"},
                            "owner_user_id": {"type": "keyword"},
                            "allowed_user_ids": {"type": "keyword"},
                            "group_ids": {"type": "keyword"},
                            "allowed_group_ids": {"type": "keyword"},
                            "visibility": {"type": "keyword"},
                            "sensitivity": {"type": "keyword"},
                            "sensitivity_rank": {"type": "integer"},
                            "expires_at": {"type": "date"},
                            "acl_policy_id": {"type": "keyword"},
                            "acl_policy_version": {"type": "integer"},
                            "allowed_role_ids": {"type": "keyword"},
                            "allowed_org_unit_ids": {"type": "keyword"},
                            "allowed_project_ids": {"type": "keyword"},
                        },
                    },
                },
            )
            logger.info("Created OpenSearch index %s", self._index_name)

    def upsert(
        self,
        *,
        chunks: list[Chunk],
        acl_metadata: dict,
    ) -> int:
        if not chunks:
            return 0

        actions = []
        for chunk in chunks:
            if chunk.id is None:
                raise RuntimeError("OpenSearch indexing requires persisted chunk IDs.")
            doc_id = _deterministic_doc_id(chunk.document_id, chunk.chunk_index)
            action = {
                "_index": self._index_name,
                "_id": str(doc_id),
                "_source": {
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
                    "acl_policy_id": acl_metadata.get("acl_policy_id", ""),
                    "acl_policy_version": acl_metadata.get("acl_policy_version", 1),
                    "allowed_role_ids": acl_metadata.get("allowed_role_ids", []),
                    "allowed_org_unit_ids": acl_metadata.get("allowed_org_unit_ids", []),
                    "allowed_project_ids": acl_metadata.get("allowed_project_ids", []),
                },
            }
            actions.append(action)

        if self._mock:
            # Capture the bulk body for test assertions without calling OpenSearch
            body: list[dict] = []
            for action in actions:
                body.append({"index": {"_index": action["_index"], "_id": action["_id"]}})
                body.append(action["_source"])
            self._last_bulk_body = body
            return len(actions)

        client = self._ensure_client()
        success, errors = bulk(client, actions, raise_on_error=True)

        if errors:
            logger.error("OpenSearch bulk indexing had errors: %s", errors)

        logger.info("Upserted %d docs to OpenSearch index %s", len(actions), self._index_name)
        return len(actions)


def _deterministic_doc_id(document_id: UUID, chunk_index: int) -> UUID:
    """Deterministic UUID for a chunk's OpenSearch doc from (document_id, chunk_index)."""
    from uuid import uuid5

    _NS = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    return uuid5(_NS, f"os:{document_id}:{chunk_index}")
