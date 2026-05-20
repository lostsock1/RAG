from __future__ import annotations

from app.services.retrieval.base import RetrievalHit, RetrievalQuery


class OpenSearchRetriever:
    def __init__(self, *, client: object, index_name: str) -> None:
        self._client = client
        self._index_name = index_name

    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        if not query.allowed_document_ids:
            return []

        response = self._client.search(
            index=self._index_name,
            body={
                "query": {
                    "bool": {
                        "must": [_build_text_clause(query.query)],
                        "filter": [{"terms": {"document_id": query.allowed_document_ids}}],
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
