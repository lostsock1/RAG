# Phase 4 Reranker Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a model-swappable reranker seam to the retrieval pipeline, wire a real `bge-reranker-v2-m3` adapter behind config, and preserve exact-query bypass behavior.

**Architecture:** Keep reranking inside the retrieval layer, after fusion and before final result selection. Exact/quoted queries continue down the lexical-only lane and skip reranking entirely. Runtime wiring follows the existing search-runtime pattern: explicit configuration, truthful failure, injectable test doubles.

**Tech Stack:** Python 3.12, FastAPI, Pydantic settings, pytest, FlagEmbedding, existing OpenSearch/Qdrant retrieval stack

---

### Task 1: Define reranker interfaces and baseline tests

**Files:**
- Modify: `apps/api/app/services/retrieval/base.py`
- Create: `apps/api/app/services/retrieval/reranker.py`
- Test: `apps/api/app/tests/unit/test_reranker.py`

- [ ] **Step 1: Write the failing tests**

```python
from app.services.retrieval.base import RetrievalHit
from app.services.retrieval.reranker import StubReranker


def test_stub_reranker_preserves_input_order_and_scores() -> None:
    hits = [
        RetrievalHit(document_id="doc-1", chunk_id="chunk-a", score=1.0, text="A"),
        RetrievalHit(document_id="doc-1", chunk_id="chunk-b", score=0.5, text="B"),
    ]

    results = StubReranker().rerank(query="hello", hits=hits, top_k=2)

    assert [hit.chunk_id for hit in results] == ["chunk-a", "chunk-b"]
    assert [hit.score for hit in results] == [1.0, 0.5]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_reranker.py::test_stub_reranker_preserves_input_order_and_scores -v`
Expected: FAIL because `app.services.retrieval.reranker` or `StubReranker` does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
from __future__ import annotations

from typing import Protocol

from app.services.retrieval.base import RetrievalHit


class Reranker(Protocol):
    def rerank(self, *, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]: ...


class StubReranker:
    def rerank(self, *, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        return list(hits[:top_k])
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_reranker.py::test_stub_reranker_preserves_input_order_and_scores -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/retrieval/base.py apps/api/app/services/retrieval/reranker.py apps/api/app/tests/unit/test_reranker.py
git commit -m "feat: add retrieval reranker seam"
```

### Task 2: Wire reranker invocation into hybrid retrieval with exact bypass preserved

**Files:**
- Modify: `apps/api/app/services/retrieval/hybrid_retriever.py`
- Test: `apps/api/app/tests/unit/test_hybrid_retriever.py`

- [ ] **Step 1: Write the failing tests**

```python
class _FakeReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], int]] = []

    def rerank(self, *, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        self.calls.append((query, [hit.chunk_id or hit.document_id for hit in hits], top_k))
        return list(reversed(hits[:top_k]))


def test_hybrid_retriever_invokes_reranker_for_non_exact_query() -> None:
    ...
    reranker = _FakeReranker()
    retriever = HybridSearchRetriever(..., reranker=reranker)

    results = retriever.search(RetrievalQuery(...))

    assert reranker.calls == [("hybrid query", ["chunk-b", "chunk-a", "chunk-c"], 3)]
    assert [hit.chunk_id for hit in results] == ["chunk-c", "chunk-a", "chunk-b"]


def test_hybrid_retriever_bypasses_reranker_for_exact_query() -> None:
    ...
    reranker = _FakeReranker()
    retriever = HybridSearchRetriever(..., reranker=reranker)

    results = retriever.search(RetrievalQuery(query='"needle phrase"', ...))

    assert [hit.route for hit in results] == ["exact"]
    assert reranker.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_hybrid_retriever.py -k reranker -v`
Expected: FAIL because `HybridSearchRetriever` does not yet accept or use a reranker.

- [ ] **Step 3: Write the minimal implementation**

```python
from app.services.retrieval.reranker import StubReranker


class HybridSearchRetriever:
    def __init__(..., reranker: object | None = None, ...) -> None:
        ...
        self._reranker = reranker or StubReranker()

    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        route = self._router.classify(query.query)
        if route.mode == "exact":
            return [replace(hit, route="exact") for hit in self._lexical_retriever.search(query)[: query.top_k]]

        ...
        fused_hits = self._fuse_hits(...)
        reranked_hits = self._reranker.rerank(query=query.query, hits=fused_hits, top_k=query.top_k)
        return self._expand_parent_hits(reranked_hits)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_hybrid_retriever.py -k reranker -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/retrieval/hybrid_retriever.py apps/api/app/tests/unit/test_hybrid_retriever.py
git commit -m "feat: rerank hybrid retrieval results"
```

### Task 3: Add runtime configuration and wiring

**Files:**
- Modify: `apps/api/app/core/config.py`
- Modify: `apps/api/app/services/retrieval/runtime.py`
- Test: `apps/api/app/tests/unit/test_search_runtime.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_search_runtime_uses_stub_reranker_when_disabled(monkeypatch) -> None:
    retriever = build_search_retriever(
        settings=Settings(search_backend="hybrid", reranker_backend="disabled"),
        state=SimpleNamespace(),
    )

    assert retriever is not None
    assert retriever._reranker.__class__.__name__ == "StubReranker"


def test_search_runtime_builds_real_reranker_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr("app.services.retrieval.runtime.BgeRerankerV2M3", _FakeReranker)

    retriever = build_search_retriever(
        settings=Settings(search_backend="hybrid", reranker_backend="bge-reranker-v2-m3"),
        state=SimpleNamespace(),
    )

    assert retriever is not None
    assert retriever._reranker.__class__.__name__ == "_FakeReranker"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_search_runtime.py -k reranker -v`
Expected: FAIL because reranker settings/wiring do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
class Settings(BaseSettings):
    ...
    reranker_backend: Literal["disabled", "stub", "bge-reranker-v2-m3"] = "disabled"
    reranker_model_name: str = "BAAI/bge-reranker-v2-m3"
    reranker_batch_size: int = 8


def _build_reranker(*, settings: Settings, state: object):
    reranker = getattr(state, "search_reranker", None)
    if reranker is not None:
        return reranker
    if settings.reranker_backend in {"disabled", "stub"}:
        return StubReranker()
    if settings.reranker_backend == "bge-reranker-v2-m3":
        return BgeRerankerV2M3(model_name=settings.reranker_model_name, batch_size=settings.reranker_batch_size)
    raise RuntimeError(f"Unsupported reranker backend: {settings.reranker_backend}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_search_runtime.py -k reranker -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/config.py apps/api/app/services/retrieval/runtime.py apps/api/app/tests/unit/test_search_runtime.py
git commit -m "feat: add reranker runtime configuration"
```

### Task 4: Add real BGE reranker adapter with isolated unit tests

**Files:**
- Create: `apps/api/app/services/retrieval/bge_reranker.py`
- Test: `apps/api/app/tests/unit/test_bge_reranker.py`

- [ ] **Step 1: Write the failing tests**

```python
from app.services.retrieval.base import RetrievalHit
from app.services.retrieval.bge_reranker import BgeRerankerV2M3


class _FakeCrossEncoder:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def compute_score(self, pairs, batch_size: int = 8, max_length: int = 512):
        return [0.2, 0.9, 0.4]


def test_bge_reranker_sorts_hits_by_model_score(monkeypatch) -> None:
    monkeypatch.setattr("app.services.retrieval.bge_reranker.FlagReranker", _FakeCrossEncoder)
    reranker = BgeRerankerV2M3(model_name="fake", batch_size=8)
    hits = [
        RetrievalHit(document_id="doc-1", chunk_id="chunk-a", score=1.0, text="A"),
        RetrievalHit(document_id="doc-1", chunk_id="chunk-b", score=0.9, text="B"),
        RetrievalHit(document_id="doc-1", chunk_id="chunk-c", score=0.8, text="C"),
    ]

    results = reranker.rerank(query="q", hits=hits, top_k=2)

    assert [hit.chunk_id for hit in results] == ["chunk-b", "chunk-c"]
    assert [hit.score for hit in results] == [0.9, 0.4]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_bge_reranker.py::test_bge_reranker_sorts_hits_by_model_score -v`
Expected: FAIL because the adapter module does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
from __future__ import annotations

from dataclasses import replace

from app.services.retrieval.base import RetrievalHit


class BgeRerankerV2M3:
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", batch_size: int = 8, max_length: int = 512) -> None:
        self._model_name = model_name
        self._batch_size = batch_size
        self._max_length = max_length
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from FlagEmbedding import FlagReranker
            self._model = FlagReranker(self._model_name, use_fp16=False)

    def rerank(self, *, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        if not hits:
            return []
        self._ensure_model()
        scores = self._model.compute_score([(query, hit.text) for hit in hits], batch_size=self._batch_size, max_length=self._max_length)
        reranked = [replace(hit, score=float(score)) for hit, score in zip(hits, scores, strict=True)]
        reranked.sort(key=lambda hit: hit.score, reverse=True)
        return reranked[:top_k]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_bge_reranker.py::test_bge_reranker_sorts_hits_by_model_score -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/retrieval/bge_reranker.py apps/api/app/tests/unit/test_bge_reranker.py
git commit -m "feat: add bge reranker adapter"
```

### Task 5: Run the targeted regression set and sync project memory

**Files:**
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`

- [ ] **Step 1: Run the targeted regression suite**

Run: `pytest apps/api/app/tests/unit/test_reranker.py apps/api/app/tests/unit/test_bge_reranker.py apps/api/app/tests/unit/test_hybrid_retriever.py apps/api/app/tests/unit/test_search_runtime.py -v`
Expected: PASS

- [ ] **Step 2: Update project memory**

```markdown
- Record the reranker seam, runtime config, exact-bypass preservation, and test results in `PROJECT_STATE.md`.
- Mark the Phase 4 reranker implementation task done in `TASKS.md`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md
git commit -m "docs: record phase 4 reranker slice"
```
