# Phase 4 Context Builder Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone context-builder seam that converts ordered retrieval hits into deterministic, budgeted, citation-preserving context blocks for later LLM generation.

**Architecture:** Keep the context builder at the retrieval/generation boundary. Retrieval and reranking continue to produce ordered `RetrievalHit` values; the context builder converts them into structured context blocks plus payload metadata without introducing prompt wording or chat behavior. The first slice uses character-count budgeting and optional block-count limits to keep the implementation deterministic and dependency-light.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, existing FastAPI backend service layout

---

### Task 1: Define context-builder schemas and baseline builder behavior

**Files:**
- Create: `apps/api/app/schemas/context.py`
- Create: `apps/api/app/services/context_builder.py`
- Test: `apps/api/app/tests/unit/test_context_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
from app.schemas.context import BuildContextRequest
from app.services.context_builder import DefaultContextBuilder
from app.services.retrieval.base import RetrievalHit


def test_context_builder_preserves_order_and_metadata() -> None:
    hits = [
        RetrievalHit(
            document_id="doc-1",
            chunk_id="chunk-1",
            score=0.9,
            text="Alpha evidence",
            page_start=1,
            page_end=2,
            heading_path=["A"],
        ),
        RetrievalHit(
            document_id="doc-2",
            chunk_id="chunk-2",
            score=0.8,
            text="Beta evidence",
            page_start=3,
            page_end=4,
            heading_path=["B"],
        ),
    ]

    payload = DefaultContextBuilder().build(
        BuildContextRequest(
            hits=hits,
            document_titles={"doc-1": "Doc A", "doc-2": "Doc B"},
            max_characters=1000,
            max_blocks=None,
        )
    )

    assert [block.chunk_id for block in payload.blocks] == ["chunk-1", "chunk-2"]
    assert [block.document_title for block in payload.blocks] == ["Doc A", "Doc B"]
    assert [block.rank for block in payload.blocks] == [1, 2]
    assert payload.truncated is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_context_builder.py::test_context_builder_preserves_order_and_metadata -v`
Expected: FAIL because the context schema and builder modules do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
from pydantic import BaseModel, ConfigDict, Field


class ContextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_title: str
    chunk_id: str | None = None
    citation_id: str | None = None
    text: str
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    rank: int


class ContextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocks: list[ContextBlock] = Field(default_factory=list)
    block_count: int
    total_characters: int
    truncated: bool = False
```

```python
from dataclasses import dataclass

from app.schemas.context import ContextBlock, ContextPayload


@dataclass(slots=True)
class BuildContextRequest:
    hits: list
    document_titles: dict[str, str]
    max_characters: int
    max_blocks: int | None = None


class DefaultContextBuilder:
    def build(self, request: BuildContextRequest) -> ContextPayload:
        blocks = []
        for index, hit in enumerate(request.hits, start=1):
            blocks.append(
                ContextBlock(
                    document_id=hit.document_id,
                    document_title=request.document_titles[hit.document_id],
                    chunk_id=hit.chunk_id,
                    citation_id=hit.chunk_id,
                    text=hit.text,
                    heading_path=hit.heading_path,
                    page_start=hit.page_start,
                    page_end=hit.page_end,
                    rank=index,
                )
            )
        total_characters = sum(len(block.text) for block in blocks)
        return ContextPayload(
            blocks=blocks,
            block_count=len(blocks),
            total_characters=total_characters,
            truncated=False,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_context_builder.py::test_context_builder_preserves_order_and_metadata -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/schemas/context.py apps/api/app/services/context_builder.py apps/api/app/tests/unit/test_context_builder.py
git commit -m "feat: add context builder seam"
```

### Task 2: Add deterministic budgeting and empty/blank-input behavior

**Files:**
- Modify: `apps/api/app/services/context_builder.py`
- Test: `apps/api/app/tests/unit/test_context_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_context_builder_truncates_last_block_to_fit_budget() -> None:
    hits = [
        RetrievalHit(document_id="doc-1", chunk_id="chunk-1", score=1.0, text="abcd"),
        RetrievalHit(document_id="doc-2", chunk_id="chunk-2", score=0.9, text="efghij"),
    ]

    payload = DefaultContextBuilder().build(
        BuildContextRequest(
            hits=hits,
            document_titles={"doc-1": "Doc A", "doc-2": "Doc B"},
            max_characters=7,
            max_blocks=None,
        )
    )

    assert [block.text for block in payload.blocks] == ["abcd", "efg"]
    assert payload.total_characters == 7
    assert payload.truncated is True


def test_context_builder_skips_blank_hits_and_returns_empty_payload() -> None:
    payload = DefaultContextBuilder().build(
        BuildContextRequest(
            hits=[RetrievalHit(document_id="doc-1", chunk_id="chunk-1", score=1.0, text="   ")],
            document_titles={"doc-1": "Doc A"},
            max_characters=10,
            max_blocks=None,
        )
    )

    assert payload.blocks == []
    assert payload.block_count == 0
    assert payload.total_characters == 0
    assert payload.truncated is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_context_builder.py -k "truncates or blank" -v`
Expected: FAIL because budgeting and blank-hit filtering are not implemented yet.

- [ ] **Step 3: Write the minimal implementation**

```python
class DefaultContextBuilder:
    def build(self, request: BuildContextRequest) -> ContextPayload:
        remaining = request.max_characters
        blocks = []
        truncated = False
        next_rank = 1

        for hit in request.hits:
            if not hit.text.strip():
                continue
            if remaining <= 0:
                truncated = True
                break

            text = hit.text
            if len(text) > remaining:
                text = text[:remaining]
                truncated = True

            blocks.append(
                ContextBlock(
                    document_id=hit.document_id,
                    document_title=request.document_titles[hit.document_id],
                    chunk_id=hit.chunk_id,
                    citation_id=hit.chunk_id,
                    text=text,
                    heading_path=hit.heading_path,
                    page_start=hit.page_start,
                    page_end=hit.page_end,
                    rank=next_rank,
                )
            )
            next_rank += 1
            remaining -= len(text)
            if len(text) < len(hit.text):
                break

        return ContextPayload(
            blocks=blocks,
            block_count=len(blocks),
            total_characters=sum(len(block.text) for block in blocks),
            truncated=truncated,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_context_builder.py -k "truncates or blank" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/context_builder.py apps/api/app/tests/unit/test_context_builder.py
git commit -m "feat: add context builder budgeting"
```

### Task 3: Add block-count limit and request validation

**Files:**
- Modify: `apps/api/app/schemas/context.py`
- Modify: `apps/api/app/services/context_builder.py`
- Test: `apps/api/app/tests/unit/test_context_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest


def test_context_builder_respects_max_blocks() -> None:
    hits = [
        RetrievalHit(document_id="doc-1", chunk_id="chunk-1", score=1.0, text="A"),
        RetrievalHit(document_id="doc-2", chunk_id="chunk-2", score=0.9, text="B"),
    ]

    payload = DefaultContextBuilder().build(
        BuildContextRequest(
            hits=hits,
            document_titles={"doc-1": "Doc A", "doc-2": "Doc B"},
            max_characters=10,
            max_blocks=1,
        )
    )

    assert [block.chunk_id for block in payload.blocks] == ["chunk-1"]
    assert payload.block_count == 1
    assert payload.truncated is True


def test_context_builder_rejects_non_positive_budget() -> None:
    with pytest.raises(ValueError, match="max_characters"):
        BuildContextRequest(
            hits=[],
            document_titles={},
            max_characters=0,
            max_blocks=None,
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_context_builder.py -k "max_blocks or non_positive_budget" -v`
Expected: FAIL because block-count limiting and request validation do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
from pydantic import BaseModel, ConfigDict, Field


class BuildContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    hits: list[RetrievalHit] = Field(default_factory=list)
    document_titles: dict[str, str] = Field(default_factory=dict)
    max_characters: int = Field(ge=1)
    max_blocks: int | None = Field(default=None, ge=1)
```

```python
        for hit in request.hits:
            if request.max_blocks is not None and len(blocks) >= request.max_blocks:
                truncated = True
                break
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_context_builder.py -k "max_blocks or non_positive_budget" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/schemas/context.py apps/api/app/services/context_builder.py apps/api/app/tests/unit/test_context_builder.py
git commit -m "feat: validate context builder request limits"
```

### Task 4: Add runtime defaults and targeted documentation updates

**Files:**
- Modify: `apps/api/app/core/config.py`
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`
- Test: `apps/api/app/tests/unit/test_context_builder.py`

- [ ] **Step 1: Write the failing test**

```python
def test_context_builder_uses_configurable_defaults_via_request() -> None:
    request = BuildContextRequest(
        hits=[RetrievalHit(document_id="doc-1", chunk_id="chunk-1", score=1.0, text="abcdef")],
        document_titles={"doc-1": "Doc A"},
        max_characters=4,
        max_blocks=1,
    )

    payload = DefaultContextBuilder().build(request)

    assert payload.total_characters == 4
    assert payload.block_count == 1
```

- [ ] **Step 2: Run the test to verify it fails if defaults/path are incomplete**

Run: `pytest apps/api/app/tests/unit/test_context_builder.py::test_context_builder_uses_configurable_defaults_via_request -v`
Expected: FAIL if default/request semantics are still incomplete.

- [ ] **Step 3: Write the minimal implementation and docs update**

```python
class Settings(BaseSettings):
    ...
    context_builder_max_characters: int = 4000
    context_builder_max_blocks: int = 8
```

```markdown
- Record the context-builder seam, deterministic budgeting, and test outcome in `docs/uber-rag/PROJECT_STATE.md`.
- Mark `Implement context builder.` complete in `docs/uber-rag/TASKS.md`.
```

- [ ] **Step 4: Run the focused and full targeted suite**

Run: `pytest apps/api/app/tests/unit/test_context_builder.py -v`
Expected: PASS

Run: `pytest apps/api/app/tests/unit/test_context_builder.py apps/api/app/tests/unit/test_reranker.py apps/api/app/tests/unit/test_bge_reranker.py apps/api/app/tests/unit/test_hybrid_retriever.py apps/api/app/tests/unit/test_query_router.py apps/api/app/tests/unit/test_search_runtime.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/config.py apps/api/app/tests/unit/test_context_builder.py docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md
git commit -m "feat: add phase 4 context builder slice"
```
