# Phase 4 LLM Adapter Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone LLM backend seam with a deterministic stub backend, a real OpenAI-compatible ppq adapter, and truthful config/runtime behavior for later `/chat` work.

**Architecture:** Keep generation transport separate from retrieval and context building. Callers pass a structured generation request containing the question and `ContextPayload`; the adapter renders provider messages internally and returns a normalized response object. Runtime wiring follows the project’s existing explicit-config pattern: stub/disabled paths are intentional, and configured real backends never silently fall back.

**Tech Stack:** Python 3.12, Pydantic v2, pydantic-settings, httpx, pytest

---

### Task 1: Define generation schemas and stub backend seam

**Files:**
- Create: `apps/api/app/schemas/generation.py`
- Create: `apps/api/app/services/llm_backend.py`
- Test: `apps/api/app/tests/unit/test_llm_backend.py`

- [ ] **Step 1: Write the failing tests**

```python
from app.schemas.context import ContextPayload
from app.schemas.generation import GenerateAnswerRequest
from app.services.llm_backend import StubLlmBackend


def test_stub_llm_backend_returns_deterministic_answer() -> None:
    request = GenerateAnswerRequest(
        question="What is this about?",
        context_payload=ContextPayload(blocks=[], block_count=0, total_characters=0, truncated=False),
        model_name="stub-model",
        temperature=0.0,
        max_output_tokens=256,
    )

    response = StubLlmBackend().generate(request)

    assert response.answer_text == "Stub answer for: What is this about?"
    assert response.model_name == "stub-model"
    assert response.provider_name == "stub"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_llm_backend.py::test_stub_llm_backend_returns_deterministic_answer -v`
Expected: FAIL because generation schemas/backend module do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.context import ContextPayload


class GenerateAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    context_payload: ContextPayload
    model_name: str = Field(min_length=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=256, ge=1)


class GenerateAnswerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str
    model_name: str
    provider_name: str
    usage: dict[str, int] | None = None
```

```python
from typing import Protocol

from app.schemas.generation import GenerateAnswerRequest, GenerateAnswerResponse


class LlmBackend(Protocol):
    def generate(self, request: GenerateAnswerRequest) -> GenerateAnswerResponse: ...


class StubLlmBackend:
    def generate(self, request: GenerateAnswerRequest) -> GenerateAnswerResponse:
        return GenerateAnswerResponse(
            answer_text=f"Stub answer for: {request.question}",
            model_name=request.model_name,
            provider_name="stub",
            usage=None,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_llm_backend.py::test_stub_llm_backend_returns_deterministic_answer -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/schemas/generation.py apps/api/app/services/llm_backend.py apps/api/app/tests/unit/test_llm_backend.py
git commit -m "feat: add llm backend seam"
```

### Task 2: Add deterministic request shaping for the real ppq/OpenAI-compatible adapter

**Files:**
- Modify: `apps/api/app/services/llm_backend.py`
- Test: `apps/api/app/tests/unit/test_llm_backend.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_ppq_backend_shapes_messages_with_context_in_stable_order() -> None:
    transport = _FakeTransport(response_json={
        "choices": [{"message": {"content": "Answer text"}}],
        "model": "llama-3.3-70b",
        "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
    })
    backend = PpqLlmBackend(
        base_url="https://ppq.example/v1",
        api_key="secret",
        model_name="llama-3.3-70b",
        transport=transport,
    )

    request = GenerateAnswerRequest(
        question="What happened?",
        context_payload=ContextPayload(
            blocks=[
                ContextBlock(document_id="doc-1", document_title="Doc A", chunk_id="c1", citation_id="c1", text="Alpha", heading_path=["H1"], page_start=1, page_end=1, rank=1),
                ContextBlock(document_id="doc-2", document_title="Doc B", chunk_id="c2", citation_id="c2", text="Beta", heading_path=["H2"], page_start=2, page_end=3, rank=2),
            ],
            block_count=2,
            total_characters=9,
            truncated=False,
        ),
        model_name="llama-3.3-70b",
        temperature=0.1,
        max_output_tokens=128,
    )

    response = backend.generate(request)

    assert response.answer_text == "Answer text"
    assert response.provider_name == "ppq"
    assert transport.last_json["model"] == "llama-3.3-70b"
    assert transport.last_json["messages"][1]["content"].count("citation_id=c1") == 1
    assert transport.last_json["messages"][1]["content"].index("citation_id=c1") < transport.last_json["messages"][1]["content"].index("citation_id=c2")
    assert transport.last_json["messages"][1]["content"].endswith("Question: What happened?")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_llm_backend.py -k stable_order -v`
Expected: FAIL because the real adapter and request shaping do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
import httpx


class PpqLlmBackend:
    def __init__(self, *, base_url: str, api_key: str, model_name: str, transport: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._transport = transport or httpx.Client()

    def generate(self, request: GenerateAnswerRequest) -> GenerateAnswerResponse:
        payload = {
            "model": request.model_name,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "messages": [
                {"role": "system", "content": "Answer only from the provided sources. If evidence is missing, say so clearly."},
                {"role": "user", "content": _render_user_message(request)},
            ],
        }
        response = self._transport.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        answer_text = body["choices"][0]["message"]["content"].strip()
        return GenerateAnswerResponse(
            answer_text=answer_text,
            model_name=body.get("model", request.model_name),
            provider_name="ppq",
            usage=body.get("usage"),
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_llm_backend.py -k stable_order -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/llm_backend.py apps/api/app/tests/unit/test_llm_backend.py
git commit -m "feat: add ppq llm adapter"
```

### Task 3: Add truthful failure behavior and config validation

**Files:**
- Modify: `apps/api/app/core/config.py`
- Create: `apps/api/app/services/llm_runtime.py`
- Test: `apps/api/app/tests/unit/test_llm_runtime.py`
- Test: `apps/api/app/tests/unit/test_llm_backend.py`

- [ ] **Step 1: Write the failing tests**

```python
from app.core.config import Settings
from app.services.llm_runtime import build_llm_backend


def test_llm_runtime_uses_stub_backend_when_disabled() -> None:
    backend = build_llm_backend(settings=Settings(llm_backend="disabled"), state=object())
    assert backend.__class__.__name__ == "StubLlmBackend"


def test_llm_runtime_rejects_missing_api_key_for_ppq() -> None:
    with pytest.raises(RuntimeError, match="llm_api_key"):
        build_llm_backend(
            settings=Settings(llm_backend="ppq", llm_base_url="https://ppq.example/v1", llm_api_key=None),
            state=object(),
        )


def test_llm_runtime_rejects_unsupported_backend() -> None:
    with pytest.raises(RuntimeError, match="Unsupported LLM backend"):
        build_llm_backend(settings=Settings(llm_backend="stub"), state=SimpleNamespace(llm_backend_override="weird"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_llm_runtime.py -v`
Expected: FAIL because config fields/runtime builder do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
class Settings(BaseSettings):
    ...
    llm_backend: Literal["disabled", "stub", "ppq"] = "disabled"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model_name: str = "meta-llama/Llama-3.3-70B-Instruct"
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_max_output_tokens: int = Field(default=512, ge=1)
```

```python
def build_llm_backend(*, settings: Settings, state: object) -> LlmBackend:
    backend = getattr(state, "llm_backend", None)
    if backend is not None:
        return backend
    if settings.llm_backend in {"disabled", "stub"}:
        return StubLlmBackend()
    if settings.llm_backend == "ppq":
        if not settings.llm_base_url:
            raise RuntimeError("LLM backend 'ppq' requires llm_base_url.")
        if not settings.llm_api_key:
            raise RuntimeError("LLM backend 'ppq' requires llm_api_key.")
        return PpqLlmBackend(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model_name=settings.llm_model_name,
        )
    raise RuntimeError(f"Unsupported LLM backend: {settings.llm_backend}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_llm_runtime.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/config.py apps/api/app/services/llm_runtime.py apps/api/app/tests/unit/test_llm_runtime.py apps/api/app/tests/unit/test_llm_backend.py
git commit -m "feat: add llm runtime configuration"
```

### Task 4: Add response-normalization and empty-response failure coverage

**Files:**
- Modify: `apps/api/app/services/llm_backend.py`
- Test: `apps/api/app/tests/unit/test_llm_backend.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_ppq_backend_fails_on_empty_provider_answer() -> None:
    transport = _FakeTransport(response_json={"choices": [{"message": {"content": "   "}}], "model": "m"})
    backend = PpqLlmBackend(base_url="https://ppq.example/v1", api_key="secret", model_name="m", transport=transport)

    request = _build_request()

    with pytest.raises(RuntimeError, match="empty response"):
        backend.generate(request)


def test_ppq_backend_normalizes_usage_metadata() -> None:
    transport = _FakeTransport(response_json={
        "choices": [{"message": {"content": "Answer text"}}],
        "model": "served-model",
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    })
    backend = PpqLlmBackend(base_url="https://ppq.example/v1", api_key="secret", model_name="m", transport=transport)

    response = backend.generate(_build_request())

    assert response.model_name == "served-model"
    assert response.usage == {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_llm_backend.py -k "empty_provider_answer or normalizes_usage" -v`
Expected: FAIL because empty-response and usage normalization behavior are incomplete.

- [ ] **Step 3: Write the minimal implementation**

```python
        answer_text = body["choices"][0]["message"]["content"].strip()
        if not answer_text:
            raise RuntimeError("LLM backend returned an empty response.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_llm_backend.py -k "empty_provider_answer or normalizes_usage" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/llm_backend.py apps/api/app/tests/unit/test_llm_backend.py
git commit -m "feat: normalize llm adapter responses"
```

### Task 5: Run targeted regression and sync project memory

**Files:**
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`

- [ ] **Step 1: Run the targeted regression suite**

Run: `pytest apps/api/app/tests/unit/test_llm_backend.py apps/api/app/tests/unit/test_llm_runtime.py apps/api/app/tests/unit/test_context_builder.py apps/api/app/tests/unit/test_reranker.py apps/api/app/tests/unit/test_hybrid_retriever.py apps/api/app/tests/unit/test_query_router.py apps/api/app/tests/unit/test_search_runtime.py -v`
Expected: PASS

- [ ] **Step 2: Update project memory**

```markdown
- Record the LLM adapter seam, ppq/OpenAI-compatible adapter, truthful config behavior, and targeted verification in `docs/uber-rag/PROJECT_STATE.md`.
- Mark `Implement LLM adapter.` complete in `docs/uber-rag/TASKS.md`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md
git commit -m "docs: record phase 4 llm adapter slice"
```
