from __future__ import annotations

from dataclasses import replace
from typing import Callable

from app.services.retrieval.base import QueryEmbedder, RetrievalHit, RetrievalQuery
from app.services.retrieval.fusion import reciprocal_rank_fusion
from app.services.retrieval.reranker import Reranker, StubReranker
from app.services.retrieval.router import QueryRouter


class HybridSearchRetriever:
    def __init__(
        self,
        *,
        router: QueryRouter,
        lexical_retriever: object,
        vector_retriever: object,
        query_embedder: QueryEmbedder,
        search_sources_repository: object | None = None,
        reranker: Reranker | None = None,
        rerank_candidate_limit: int | None = None,
        fuse: Callable[[list[list[str]]], list[str]] = reciprocal_rank_fusion,
    ) -> None:
        self._router = router
        self._lexical_retriever = lexical_retriever
        self._vector_retriever = vector_retriever
        self._query_embedder = query_embedder
        self._search_sources_repository = search_sources_repository
        self._reranker = reranker or StubReranker()
        self._rerank_candidate_limit = rerank_candidate_limit
        self._fuse = fuse

    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        route = self._router.classify(query.query)
        if route.mode == "exact":
            return [
                replace(hit, route="exact")
                for hit in self._lexical_retriever.search(query)[: query.top_k]
            ]

        query_embedding = self._query_embedder.embed_query(query.query)
        lexical_hits = self._lexical_retriever.search(query)
        dense_hits = self._vector_retriever.search_dense(query, query_embedding)
        sparse_hits = self._vector_retriever.search_sparse(query, query_embedding)
        fused_hits = self._fuse_hits(
            lexical_hits=lexical_hits,
            dense_hits=dense_hits,
            sparse_hits=sparse_hits,
            top_k=self._resolve_rerank_candidate_limit(query.top_k),
        )
        expanded_hits = self._expand_parent_hits(fused_hits)
        return self._reranker.rerank(query=query.query, hits=expanded_hits, top_k=query.top_k)

    def _fuse_hits(
        self,
        *,
        lexical_hits: list[RetrievalHit],
        dense_hits: list[RetrievalHit],
        sparse_hits: list[RetrievalHit],
        top_k: int,
    ) -> list[RetrievalHit]:
        hit_by_candidate_id: dict[str, RetrievalHit] = {}
        rank_lists: list[list[str]] = []
        for hit_list in (lexical_hits, dense_hits, sparse_hits):
            candidate_ids: list[str] = []
            for hit in hit_list:
                candidate_id = hit.chunk_id or hit.document_id
                if candidate_id not in hit_by_candidate_id:
                    hit_by_candidate_id[candidate_id] = replace(hit, route="semantic")
                candidate_ids.append(candidate_id)
            rank_lists.append(candidate_ids)

        fused_ids = self._fuse(rank_lists)
        return [hit_by_candidate_id[candidate_id] for candidate_id in fused_ids[:top_k]]

    def _expand_parent_hits(self, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        if self._search_sources_repository is None:
            return hits

        child_chunk_ids = [hit.chunk_id for hit in hits if hit.chunk_id is not None]
        if not child_chunk_ids:
            return hits

        parent_by_child_id = self._search_sources_repository.get_parent_chunks_by_child_ids(
            child_chunk_ids=child_chunk_ids
        )
        if not parent_by_child_id:
            return hits

        expanded_hits: list[RetrievalHit] = []
        seen_candidate_ids: set[str] = set()
        for hit in hits:
            if hit.chunk_id is None:
                candidate_id = hit.document_id
                if candidate_id in seen_candidate_ids:
                    continue
                expanded_hits.append(hit)
                seen_candidate_ids.add(candidate_id)
                continue

            parent = parent_by_child_id.get(hit.chunk_id)
            if parent is None:
                candidate_id = hit.chunk_id
                if candidate_id in seen_candidate_ids:
                    continue
                expanded_hits.append(hit)
                seen_candidate_ids.add(candidate_id)
                continue

            parent_hit = RetrievalHit(
                document_id=str(parent["document_id"]),
                chunk_id=str(parent["chunk_id"]),
                score=hit.score,
                text=str(parent["text"]),
                page_start=parent.get("page_start"),
                page_end=parent.get("page_end"),
                heading_path=list(parent.get("heading_path", [])),
                route=hit.route,
            )
            candidate_id = parent_hit.chunk_id or parent_hit.document_id
            if candidate_id in seen_candidate_ids:
                continue
            expanded_hits.append(parent_hit)
            seen_candidate_ids.add(candidate_id)

        return expanded_hits

    def _resolve_rerank_candidate_limit(self, top_k: int) -> int:
        if self._rerank_candidate_limit is None:
            return top_k
        return max(top_k, self._rerank_candidate_limit)


__all__ = ["HybridSearchRetriever"]
