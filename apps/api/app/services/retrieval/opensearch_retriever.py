from __future__ import annotations

from app.services.retrieval.acl_filter import build_opensearch_acl_filter
from app.services.retrieval.base import RetrievalHit, RetrievalQuery


class OpenSearchRetriever:
    def __init__(self, *, client: object, index_name: str) -> None:
        self._client = client
        self._index_name = index_name

    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        acl_filter = build_opensearch_acl_filter(
            tenant_id=query.tenant_id,
            user_id=query.user_id,
            group_ids=query.group_ids,
        )

        # Opt-in narrow filter: if caller supplied allowed_document_ids, add it
        # on top of the ACL filter (intersection, not replacement).
        if query.allowed_document_ids:
            acl_filter = acl_filter + [{"terms": {"document_id": query.allowed_document_ids}}]

        response = self._client.search(
            index=self._index_name,
            body={
                "query": {
                    "bool": {
                        "must": [_build_text_clause(query.query)],
                        "filter": acl_filter,
                    }
                },
                "size": query.top_k,
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        return [_map_opensearch_hit(hit) for hit in hits]


def _build_text_clause(raw_query: str) -> dict:
    normalized = raw_query.strip()
    if normalized.startswith('"') and normalized.endswith('"') and len(normalized) >= 2:
        return {"match_phrase": {"text": normalized[1:-1]}}
    return {"match": {"text": raw_query}}


def _map_opensearch_hit(hit: dict) -> RetrievalHit:
    source = hit.get("_source", {})
    document_id = source["document_id"]
    chunk_id = source.get("chunk_id")
    return RetrievalHit(
        document_id=document_id,
        chunk_id=chunk_id,
        score=float(hit.get("_score", 0.0)),
        text=source.get("text", ""),
        page_start=source.get("page_start"),
        page_end=source.get("page_end"),
        heading_path=source.get("heading_path", []),
    )
