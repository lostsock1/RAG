# Phase 3 Search MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the real Phase 3 Search MVP so `/api/v1/search` returns ranked, ACL-filtered, citation-bound chunk hits through the public API.

**Architecture:** Keep the current thin `/search` route and replace the null retriever seam with a composable retrieval stack: query router → lexical/vector candidate retrieval → fusion → parent expansion → response shaping. Preserve the current security model by constructing ACL constraints before every backend query and retaining post-retrieval filtering as defense in depth.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy repositories, OpenSearch, Qdrant, pytest

---

## File structure

- Create: `apps/api/app/services/retrieval/router.py` — classify queries into exact / semantic / synthesis routes and latency tiers.
- Create: `apps/api/app/services/retrieval/fusion.py` — rank fusion helpers (start with RRF unless the entry-gate research/ADR says otherwise).
- Create: `apps/api/app/services/retrieval/opensearch_retriever.py` — lexical and phrase retrieval adapter with ACL filters.
- Create: `apps/api/app/services/retrieval/qdrant_retriever.py` — dense and sparse retrieval adapter with ACL filters.
- Create: `apps/api/app/services/retrieval/hybrid_retriever.py` — orchestrates router, adapters, fusion, and parent expansion.
- Create: `apps/api/app/repositories/search_sources.py` — chunk/source fetch helpers for parent expansion and source viewer.
- Create: `apps/api/app/api/routes/search_sources.py` — source viewer endpoint.
- Modify: `apps/api/app/services/retrieval/base.py` — richer query/result contracts.
- Modify: `apps/api/app/services/retrieval/search_service.py` — route metadata, stable citation fields, source-viewer linkage.
- Modify: `apps/api/app/schemas/search.py` — response fields for route, citations, and source handles.
- Modify: `apps/api/app/api/routes/search.py` — keep route thin but wire the richer service contract.
- Modify: `apps/api/app/main.py` — construct the real search retriever from app settings.
- Modify: `apps/api/app/core/config.py` — search config for top-k defaults, backend names, and index/collection names.
- Modify: `apps/api/app/api/router.py` — register source viewer route.
- Modify: `docs/uber-rag/API_CONTRACT.md` — phase-3 contract truthfulness.
- Modify: `docs/uber-rag/api/openapi.yaml` — `/search` and source viewer schema/endpoint updates.
- Modify: `docs/uber-rag/PROJECT_STATE.md` and `docs/uber-rag/TASKS.md` — record progress after landing code.
- Create: `apps/api/app/tests/unit/test_query_router.py`
- Create: `apps/api/app/tests/unit/test_fusion.py`
- Create: `apps/api/app/tests/unit/test_opensearch_retriever.py`
- Create: `apps/api/app/tests/unit/test_qdrant_retriever.py`
- Create: `apps/api/app/tests/unit/test_hybrid_retriever.py`
- Create: `apps/api/app/tests/unit/test_search_sources_repository.py`
- Modify: `apps/api/app/tests/integration/test_search_route.py`
- Create: `apps/api/app/tests/integration/test_search_source_viewer.py`
- Modify: `apps/api/app/tests/unit/test_phase1_docs.py`
- Create: `docs/uber-rag/research/2026-05-20-phase-3-entry.md`
- Modify: `docs/uber-rag/STACK_REFERENCES.md`

## Scope notes

- `ROADMAP.md:150-172` is the source of truth for Phase 3. Do **not** implement reranking or answer generation in this slice.
- `TASKS.md:93-97` currently lists reranker/context-builder work under Phase 3; reconcile that mismatch in the memory update instead of silently expanding scope.
- Phase-entry research is mandatory before code execution. If `search/deepeye` is still unavailable, stop after Task 1 and get explicit approval for degraded research.

### Task 1: Close the mandatory Phase 3 entry gate

**Files:**
- Create: `docs/uber-rag/research/2026-05-20-phase-3-entry.md`
- Modify: `docs/uber-rag/STACK_REFERENCES.md`
- Modify (only if required): `docs/uber-rag/adr/0014-search-fusion-choice.md`

- [ ] **Step 1: Write the failing documentation test**

```python
from pathlib import Path


def test_phase3_entry_note_exists_and_mentions_fusion_choice() -> None:
    text = Path("docs/uber-rag/research/2026-05-20-phase-3-entry.md").read_text()
    assert "Qdrant" in text
    assert "OpenSearch" in text
    assert "RRF" in text or "DBSF" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_phase1_docs.py -k phase3 -v`
Expected: FAIL because the Phase 3 entry note assertion does not exist yet.

- [ ] **Step 3: Write the research note and reference updates**

```markdown
# Phase 3 entry review

- Checked Qdrant hybrid retrieval/filtering docs
- Checked OpenSearch hybrid/phrase/BM25 docs
- Checked BGE-M3 model card for status changes
- Compared RRF vs DBSF evidence for first implementation choice
- Decision for implementation start: RRF unless ADR reopened by research findings
```

- [ ] **Step 4: Run docs test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_phase1_docs.py -k phase3 -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/uber-rag/research/2026-05-20-phase-3-entry.md docs/uber-rag/STACK_REFERENCES.md apps/api/app/tests/unit/test_phase1_docs.py
git commit -m "docs: close phase 3 entry review"
```

### Task 2: Expand the retrieval contracts and response schema

**Files:**
- Modify: `apps/api/app/services/retrieval/base.py`
- Modify: `apps/api/app/schemas/search.py`
- Modify: `apps/api/app/services/retrieval/search_service.py`
- Test: `apps/api/app/tests/unit/test_hybrid_retriever.py`

- [ ] **Step 1: Write the failing schema/contract test**

```python
from app.schemas.search import SearchHitResponse


def test_search_hit_response_exposes_citation_and_route_metadata() -> None:
    payload = SearchHitResponse.model_validate(
        {
            "document_id": "doc-1",
            "document_title": "Doc",
            "source_type": "loose_document",
            "chunk_id": "chunk-1",
            "score": 0.9,
            "text": "body",
            "heading_path": ["A"],
            "citation_id": "chunk-1",
            "source_viewer_url": "/api/v1/search/sources/chunk-1",
            "route": "exact",
        }
    )
    assert payload.citation_id == "chunk-1"
    assert payload.route == "exact"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_hybrid_retriever.py -k citation -v`
Expected: FAIL because the new schema fields do not exist.

- [ ] **Step 3: Write the minimal contract expansion**

```python
@dataclass(slots=True)
class RetrievalHit:
    document_id: str
    chunk_id: str | None
    score: float
    text: str
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = field(default_factory=list)
    route: str = "semantic"
    parent_chunk_id: str | None = None


class SearchHitResponse(BaseModel):
    document_id: str
    document_title: str
    source_type: str
    chunk_id: str | None = None
    citation_id: str | None = None
    source_viewer_url: str | None = None
    route: str
    score: float
    text: str
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_hybrid_retriever.py -k citation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/retrieval/base.py apps/api/app/schemas/search.py apps/api/app/services/retrieval/search_service.py apps/api/app/tests/unit/test_hybrid_retriever.py
git commit -m "feat: expand search retrieval contracts"
```

### Task 3: Implement the query router

**Files:**
- Create: `apps/api/app/services/retrieval/router.py`
- Test: `apps/api/app/tests/unit/test_query_router.py`

- [ ] **Step 1: Write the failing router test**

```python
from app.services.retrieval.router import QueryRouter


def test_query_router_sends_quoted_query_to_exact_route() -> None:
    route = QueryRouter().classify('"needle phrase"')
    assert route.mode == "exact"
    assert route.latency_tier == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_query_router.py -v`
Expected: FAIL because `router.py` does not exist.

- [ ] **Step 3: Write the minimal router**

```python
from dataclasses import dataclass


@dataclass(slots=True)
class QueryRoute:
    mode: str
    latency_tier: int


class QueryRouter:
    def classify(self, query: str) -> QueryRoute:
        normalized = query.strip()
        if normalized.startswith('"') and normalized.endswith('"'):
            return QueryRoute(mode="exact", latency_tier=1)
        return QueryRoute(mode="semantic", latency_tier=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_query_router.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/retrieval/router.py apps/api/app/tests/unit/test_query_router.py
git commit -m "feat: add search query router"
```

### Task 4: Implement fusion helpers

**Files:**
- Create: `apps/api/app/services/retrieval/fusion.py`
- Test: `apps/api/app/tests/unit/test_fusion.py`

- [ ] **Step 1: Write the failing fusion test**

```python
from app.services.retrieval.fusion import reciprocal_rank_fusion


def test_rrf_prefers_hits_present_in_multiple_rank_lists() -> None:
    fused = reciprocal_rank_fusion([
        ["chunk-a", "chunk-b"],
        ["chunk-b", "chunk-c"],
    ])
    assert fused[0] == "chunk-b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_fusion.py -v`
Expected: FAIL because `fusion.py` does not exist.

- [ ] **Step 3: Write the minimal RRF implementation**

```python
def reciprocal_rank_fusion(rank_lists: list[list[str]], k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for rank_list in rank_lists:
        for rank, item in enumerate(rank_list, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return [item for item, _ in sorted(scores.items(), key=lambda pair: pair[1], reverse=True)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_fusion.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/retrieval/fusion.py apps/api/app/tests/unit/test_fusion.py
git commit -m "feat: add reciprocal rank fusion"
```

### Task 5: Implement backend retrieval adapters with ACL filters

**Files:**
- Create: `apps/api/app/services/retrieval/opensearch_retriever.py`
- Create: `apps/api/app/services/retrieval/qdrant_retriever.py`
- Test: `apps/api/app/tests/unit/test_opensearch_retriever.py`
- Test: `apps/api/app/tests/unit/test_qdrant_retriever.py`

- [ ] **Step 1: Write the failing adapter tests**

```python
def test_opensearch_retriever_includes_allowed_document_filter() -> None:
    ...


def test_qdrant_retriever_includes_allowed_document_filter() -> None:
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_opensearch_retriever.py apps/api/app/tests/unit/test_qdrant_retriever.py -v`
Expected: FAIL because the adapters do not exist.

- [ ] **Step 3: Write the minimal adapters**

```python
class OpenSearchRetriever:
    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        body = {
            "query": {
                "bool": {
                    "must": [{"match": {"text": query.query}}],
                    "filter": [{"terms": {"document_id": query.allowed_document_ids}}],
                }
            },
            "size": query.top_k,
        }
        ...


class QdrantRetriever:
    def search_dense(self, query: RetrievalQuery) -> list[RetrievalHit]:
        query_filter = {"must": [{"key": "document_id", "match": {"any": query.allowed_document_ids}}]}
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_opensearch_retriever.py apps/api/app/tests/unit/test_qdrant_retriever.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/retrieval/opensearch_retriever.py apps/api/app/services/retrieval/qdrant_retriever.py apps/api/app/tests/unit/test_opensearch_retriever.py apps/api/app/tests/unit/test_qdrant_retriever.py
git commit -m "feat: add acl-safe search retriever adapters"
```

### Task 6: Implement the hybrid retriever and parent expansion

**Files:**
- Create: `apps/api/app/services/retrieval/hybrid_retriever.py`
- Create: `apps/api/app/repositories/search_sources.py`
- Test: `apps/api/app/tests/unit/test_hybrid_retriever.py`
- Test: `apps/api/app/tests/unit/test_search_sources_repository.py`

- [ ] **Step 1: Write the failing orchestration test**

```python
def test_hybrid_retriever_uses_exact_lane_without_dense_search_for_quoted_query() -> None:
    ...


def test_parent_expansion_fetches_parent_chunk_for_synthesis_route() -> None:
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_hybrid_retriever.py apps/api/app/tests/unit/test_search_sources_repository.py -v`
Expected: FAIL because the hybrid retriever and source repository do not exist.

- [ ] **Step 3: Write the minimal orchestrator**

```python
class HybridSearchRetriever:
    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        route = self._router.classify(query.query)
        if route.mode == "exact":
            hits = self._lexical.search(query)
            return [replace(hit, route="exact") for hit in hits]
        lexical_hits = self._lexical.search(query)
        dense_hits = self._vector.search_dense(query)
        sparse_hits = self._vector.search_sparse(query)
        fused = self._fuse(lexical_hits, dense_hits, sparse_hits)
        return self._expand_parents_if_needed(fused, route)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_hybrid_retriever.py apps/api/app/tests/unit/test_search_sources_repository.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/retrieval/hybrid_retriever.py apps/api/app/repositories/search_sources.py apps/api/app/tests/unit/test_hybrid_retriever.py apps/api/app/tests/unit/test_search_sources_repository.py
git commit -m "feat: add hybrid retrieval orchestration"
```

### Task 7: Expose the Phase 3 API surface

**Files:**
- Modify: `apps/api/app/api/routes/search.py`
- Create: `apps/api/app/api/routes/search_sources.py`
- Modify: `apps/api/app/api/router.py`
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/app/core/config.py`
- Modify: `apps/api/app/schemas/search.py`
- Modify: `docs/uber-rag/API_CONTRACT.md`
- Modify: `docs/uber-rag/api/openapi.yaml`
- Modify: `apps/api/app/tests/integration/test_search_route.py`
- Create: `apps/api/app/tests/integration/test_search_source_viewer.py`
- Modify: `apps/api/app/tests/unit/test_phase1_docs.py`

- [ ] **Step 1: Write the failing API tests**

```python
def test_search_response_includes_citation_pointer_and_route() -> None:
    ...


def test_source_viewer_returns_chunk_with_surrounding_context() -> None:
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/api/app/tests/integration/test_search_route.py apps/api/app/tests/integration/test_search_source_viewer.py apps/api/app/tests/unit/test_phase1_docs.py -v`
Expected: FAIL because the API contract and source-viewer endpoint are not implemented.

- [ ] **Step 3: Write the minimal API wiring**

```python
@router.get('/sources/{chunk_id}')
def get_search_source(chunk_id: str, context: RequestContext = Depends(require_scopes(['documents:read']))):
    return SearchSourceService(...).get_source(chunk_id=chunk_id, context=context)
```

```yaml
/api/v1/search:
  post:
    responses:
      "200":
        description: ACL-filtered ranked chunk hits
/api/v1/search/sources/{chunk_id}:
  get:
    responses:
      "200":
        description: Source chunk with surrounding context
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/api/app/tests/integration/test_search_route.py apps/api/app/tests/integration/test_search_source_viewer.py apps/api/app/tests/unit/test_phase1_docs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/api/routes/search.py apps/api/app/api/routes/search_sources.py apps/api/app/api/router.py apps/api/app/main.py apps/api/app/core/config.py apps/api/app/schemas/search.py docs/uber-rag/API_CONTRACT.md docs/uber-rag/api/openapi.yaml apps/api/app/tests/integration/test_search_route.py apps/api/app/tests/integration/test_search_source_viewer.py apps/api/app/tests/unit/test_phase1_docs.py
git commit -m "feat: expose search mvp api"
```

### Task 8: Verify, review, and update project memory

**Files:**
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`
- Review input: all changed retrieval/search files

- [ ] **Step 1: Run the targeted verification suite**

Run: `pytest apps/api/app/tests/unit/test_query_router.py apps/api/app/tests/unit/test_fusion.py apps/api/app/tests/unit/test_opensearch_retriever.py apps/api/app/tests/unit/test_qdrant_retriever.py apps/api/app/tests/unit/test_hybrid_retriever.py apps/api/app/tests/unit/test_search_sources_repository.py apps/api/app/tests/integration/test_search_route.py apps/api/app/tests/integration/test_search_source_viewer.py apps/api/app/tests/unit/test_phase1_docs.py -v`
Expected: PASS

- [ ] **Step 2: Run the broader backend regression**

Run: `pytest apps/api/app/tests -q`
Expected: PASS

- [ ] **Step 3: Update project memory truthfully**

```markdown
- Phase 3 search MVP started/landed
- Query router, retrieval adapters, fusion, and source viewer status
- Any scope held for Phase 4 (reranker, generation, verifier)
```

- [ ] **Step 4: Request mandatory external review**

Run: dispatch `RAG/uber-rag-reviewer` on the final diff.
Expected: PASS or actionable must-fix list before completion.

- [ ] **Step 5: Commit**

```bash
git add docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md
git commit -m "docs: record phase 3 search mvp status"
```

## Self-review

- Spec coverage: covers entry gate, query router, ACL filter construction, hybrid fusion, parent expansion, citation pointers, `/search`, and source viewer.
- Placeholder scan: one intentional stop condition remains — if DeepEye is unavailable, phase-entry research requires explicit degraded-mode approval.
- Consistency: this plan keeps reranking and answer generation out of Phase 3 per `ROADMAP.md:150-172`.

## Recommended execution order

1. Task 1 only until the phase-entry review is closed.
2. Tasks 2-4 to land contracts/router/fusion.
3. Tasks 5-7 to land backend retrieval and API wiring.
4. Task 8 for verification, memory update, and reviewer signoff.
