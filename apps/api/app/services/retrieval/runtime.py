from __future__ import annotations

from opensearchpy import OpenSearch
from qdrant_client import QdrantClient

from app.core.config import Settings
from app.repositories.search_sources import get_parent_chunks_by_child_ids
from app.services.retrieval.bge_reranker import BgeRerankerV2M3
from app.services.retrieval.hybrid_retriever import HybridSearchRetriever
from app.services.retrieval.opensearch_retriever import OpenSearchRetriever
from app.services.retrieval.qdrant_retriever import QdrantRetriever
from app.services.retrieval.query_embedder import BgeM3QueryEmbedder
from app.services.retrieval.reranker import StubReranker
from app.services.retrieval.router import QueryRouter


def build_search_retriever(*, settings: Settings, state: object) -> HybridSearchRetriever | None:
    if settings.search_backend != "hybrid":
        return None

    lexical_client = getattr(state, "search_lexical_client", None)
    if lexical_client is None:
        auth = None
        if settings.opensearch_username and settings.opensearch_password:
            auth = (settings.opensearch_username, settings.opensearch_password)
        open_search_kwargs = {
            "hosts": [{"host": settings.opensearch_host, "port": settings.opensearch_port}],
            "http_auth": auth,
            "use_ssl": settings.opensearch_use_ssl,
            "verify_certs": settings.opensearch_verify_certs,
        }
        if not settings.opensearch_verify_certs:
            open_search_kwargs["ssl_show_warn"] = False
        lexical_client = OpenSearch(**open_search_kwargs)

    vector_client = getattr(state, "search_vector_client", None)
    if vector_client is None:
        vector_client = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            api_key=settings.qdrant_api_key,
        )

    query_embedder = getattr(state, "search_query_embedder", None) or BgeM3QueryEmbedder()
    reranker = _build_reranker(settings=settings, state=state)

    return HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=OpenSearchRetriever(client=lexical_client, index_name=settings.opensearch_index_name),
        vector_retriever=QdrantRetriever(client=vector_client, collection_name=settings.qdrant_collection_name),
        query_embedder=query_embedder,
        search_sources_repository=_SearchSourcesRepository(),
        reranker=reranker,
        rerank_candidate_limit=settings.reranker_candidate_limit,
    )


class _SearchSourcesRepository:
    def get_parent_chunks_by_child_ids(self, *, child_chunk_ids: list[str]) -> dict[str, dict[str, object]]:
        return get_parent_chunks_by_child_ids(child_chunk_ids=child_chunk_ids)


def _build_reranker(*, settings: Settings, state: object) -> object:
    reranker = getattr(state, "search_reranker", None)
    if reranker is not None:
        return reranker
    if settings.reranker_backend in {"disabled", "stub"}:
        return StubReranker()
    if settings.reranker_backend == "bge-reranker-v2-m3":
        return BgeRerankerV2M3(
            model_name=settings.reranker_model_name,
            batch_size=settings.reranker_batch_size,
            max_length=settings.reranker_max_length,
        )
    raise RuntimeError(f"Unsupported reranker backend: {settings.reranker_backend}")
