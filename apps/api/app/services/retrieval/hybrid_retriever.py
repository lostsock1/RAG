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
        parent_expansion_enabled: bool = True,
        parent_expansion_max_characters: int = 2048,
        fuse: Callable[[list[list[str]]], list[str]] = reciprocal_rank_fusion,
    ) -> None:
        self._router = router
        self._lexical_retriever = lexical_retriever
        self._vector_retriever = vector_retriever
        self._query_embedder = query_embedder
        self._search_sources_repository = search_sources_repository
        self._reranker = reranker or StubReranker()
        self._rerank_candidate_limit = rerank_candidate_limit
        self._parent_expansion_enabled = parent_expansion_enabled
        self._parent_expansion_max_characters = parent_expansion_max_characters
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
        if not fused_hits:
            return []
        # E1: rerank precise LEAF texts over the full candidate pool, then
        # expand to parent context — never the other way around (a
        # whole-document parent blob defeats cross-encoder precision and its
        # max_length window). Reranking the full pool lets expansion dedupe
        # shared parents and still backfill to top_k.
        ranked_hits = self._reranker.rerank(
            query=query.query, hits=fused_hits, top_k=len(fused_hits)
        )
        return self._expand_parent_hits(ranked_hits, top_k=query.top_k)

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

    def _expand_parent_hits(self, hits: list[RetrievalHit], *, top_k: int) -> list[RetrievalHit]:
        """E1 parent-child expansion: replace each leaf hit's TEXT with a
        capped window of its parent chunk's text while keeping the leaf's
        identity (chunk_id for citations, heading path, pages).

        Dedupe is content-true: a hit is dropped only when its (expanded)
        text is contained in an already-kept hit's text — never the other
        way around. Keying dedupe on the parent id instead would collapse
        every leaf of a document into one result under the loose profile
        (parent = whole document) and lose distinct evidence spans; the E1
        eval gate measured exactly that (recall@10 1.0 -> 0.9). Containment
        can't lose a ground-truth span: every span of a dropped text is
        present in the survivor. Later candidates backfill to top_k."""
        if not self._parent_expansion_enabled or self._search_sources_repository is None:
            return hits[:top_k]

        child_chunk_ids = [hit.chunk_id for hit in hits if hit.chunk_id is not None]
        parent_by_child_id: dict[str, dict[str, object]] = {}
        if child_chunk_ids:
            parent_by_child_id = self._search_sources_repository.get_parent_chunks_by_child_ids(
                child_chunk_ids=child_chunk_ids
            )

        expanded_hits: list[RetrievalHit] = []
        for hit in hits:
            if len(expanded_hits) >= top_k:
                break

            parent = parent_by_child_id.get(hit.chunk_id) if hit.chunk_id is not None else None
            if parent is None:
                candidate = hit
            else:
                candidate = replace(
                    hit,
                    text=self._expanded_text(leaf_text=hit.text, parent_text=str(parent["text"])),
                )
            if candidate.text and any(candidate.text in kept.text for kept in expanded_hits):
                continue
            expanded_hits.append(candidate)

        return expanded_hits

    def _expanded_text(self, *, leaf_text: str, parent_text: str) -> str:
        """Capped parent window that must contain the leaf evidence — the
        chunker truncates parents at PARENT_MAX_CHARS, so a leaf can be
        absent from its parent's text; expansion must never swap evidence
        for a text that lost it."""
        cap = self._parent_expansion_max_characters
        if not leaf_text or leaf_text not in parent_text:
            return leaf_text
        if len(parent_text) <= cap:
            return parent_text
        if len(leaf_text) >= cap:
            return leaf_text
        leaf_start = parent_text.index(leaf_text)
        margin = (cap - len(leaf_text)) // 2
        window_start = min(max(leaf_start - margin, 0), len(parent_text) - cap)
        return parent_text[window_start : window_start + cap]

    def _resolve_rerank_candidate_limit(self, top_k: int) -> int:
        if self._rerank_candidate_limit is None:
            return top_k
        return max(top_k, self._rerank_candidate_limit)


__all__ = ["HybridSearchRetriever"]
