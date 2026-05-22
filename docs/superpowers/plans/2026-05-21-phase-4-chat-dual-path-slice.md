# Phase 4 Chat Dual-Path Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first user-facing `/chat` API with both non-streaming and streaming paths backed by one shared orchestration service.

**Architecture:** Keep chat orchestration in a dedicated `ChatService` that composes the existing retrieval, context-builder, and LLM-backend seams. Expose two thin route adapters: one JSON response path and one streaming path that emits a truthful minimal event sequence (`start`, `answer`, `done`) without inventing token streaming before the provider path supports it.

**Tech Stack:** FastAPI, Pydantic v2, StreamingResponse, pytest, existing retrieval/context/LLM seams

---

### Task 1: Add chat schemas and the shared `ChatService` seam

**Files:**
- Create: `apps/api/app/schemas/chat.py`
- Create: `apps/api/app/services/chat_service.py`
- Test: `apps/api/app/tests/unit/test_chat_service.py`

- [ ] **Step 1: Write the failing tests**

```python
from app.core.request_context import RequestContext
from app.schemas.chat import ChatRequest
from app.schemas.context import ContextPayload
from app.schemas.generation import GenerateAnswerResponse
from app.services.chat_service import ChatService


def test_chat_service_calls_retrieval_context_builder_and_llm_in_order() -> None:
    service = ChatService(
        retriever=_FakeRetriever(),
        context_builder=_FakeContextBuilder(),
        llm_backend=_FakeLlmBackend(),
    )

    result = service.answer(
        context=RequestContext(
            tenant_id="tenant-1",
            user_id="user-1",
            group_ids=[],
            roles=["reader"],
            scopes=["documents:read"],
        ),
        payload=ChatRequest(question="What happened?", top_k=3),
    )

    assert result.answer_text == "Answer"
    assert result.provider_name == "stub"
    assert result.context_block_count == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_chat_service.py::test_chat_service_calls_retrieval_context_builder_and_llm_in_order -v`
Expected: FAIL because chat schemas/service do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str
    model_name: str
    provider_name: str
    context_block_count: int
    usage: dict[str, int] | None = None
```

```python
class ChatService:
    def __init__(self, *, retriever, context_builder, llm_backend) -> None:
        self._retriever = retriever
        self._context_builder = context_builder
        self._llm_backend = llm_backend

    def answer(self, *, context: RequestContext, payload: ChatRequest) -> ChatResponse:
        hits = self._retriever.search(...)
        context_payload = self._context_builder.build(...)
        llm_response = self._llm_backend.generate(...)
        return ChatResponse(...)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_chat_service.py::test_chat_service_calls_retrieval_context_builder_and_llm_in_order -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/schemas/chat.py apps/api/app/services/chat_service.py apps/api/app/tests/unit/test_chat_service.py
git commit -m "feat: add chat orchestration service"
```

### Task 2: Add truthful non-streaming `/chat`

**Files:**
- Create: `apps/api/app/api/routes/chat.py`
- Modify: `apps/api/app/api/router.py`
- Test: `apps/api/app/tests/integration/test_chat_route.py`

- [ ] **Step 1: Write the failing test**

```python
def test_chat_route_returns_answer_payload() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={"question": "What happened?", "top_k": 3},
            headers=_dev_auth_headers(...),
        )

    assert response.status_code == 200
    assert response.json()["answer_text"] == "Answer"
    assert response.json()["provider_name"] == "stub"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest apps/api/app/tests/integration/test_chat_route.py::test_chat_route_returns_answer_payload -v`
Expected: FAIL because the route does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
router = APIRouter()


@router.post("", response_model=ChatResponse)
def chat_route(
    request: Request,
    payload: ChatRequest,
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> ChatResponse:
    retriever = getattr(request.app.state, "search_retriever", None)
    llm_backend = getattr(request.app.state, "llm_backend", None)
    if retriever is None:
        raise HTTPException(status_code=503, detail="Search retrieval is not configured yet.")
    if llm_backend is None:
        raise HTTPException(status_code=503, detail="LLM backend is not configured yet.")
    return ChatService(...).answer(context=context, payload=payload)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest apps/api/app/tests/integration/test_chat_route.py::test_chat_route_returns_answer_payload -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/api/routes/chat.py apps/api/app/api/router.py apps/api/app/tests/integration/test_chat_route.py
git commit -m "feat: add non-streaming chat route"
```

### Task 3: Add minimal streaming `/chat/stream` using the same service path

**Files:**
- Modify: `apps/api/app/api/routes/chat.py`
- Test: `apps/api/app/tests/integration/test_chat_route.py`

- [ ] **Step 1: Write the failing test**

```python
def test_chat_stream_route_emits_start_answer_done_events() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={"question": "What happened?", "top_k": 3},
            headers=_dev_auth_headers(...),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: start" in response.text
    assert "event: answer" in response.text
    assert "event: done" in response.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest apps/api/app/tests/integration/test_chat_route.py::test_chat_stream_route_emits_start_answer_done_events -v`
Expected: FAIL because the streaming route does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
from fastapi.responses import StreamingResponse


@router.post("/stream")
def chat_stream_route(...):
    result = ChatService(...).answer(context=context, payload=payload)

    def _events():
        yield "event: start\ndata: {}\n\n"
        yield f"event: answer\ndata: {json.dumps(result.model_dump())}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(_events(), media_type="text/event-stream")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest apps/api/app/tests/integration/test_chat_route.py::test_chat_stream_route_emits_start_answer_done_events -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/api/routes/chat.py apps/api/app/tests/integration/test_chat_route.py
git commit -m "feat: add streaming chat route"
```

### Task 4: Add truthful failure-path coverage and shared-service reuse checks

**Files:**
- Modify: `apps/api/app/tests/unit/test_chat_service.py`
- Modify: `apps/api/app/tests/integration/test_chat_route.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_chat_route_returns_503_when_retriever_missing() -> None:
    ...
    assert response.status_code == 503
    assert response.json()["detail"] == "Search retrieval is not configured yet."


def test_chat_route_returns_503_when_llm_backend_missing() -> None:
    ...
    assert response.status_code == 503
    assert response.json()["detail"] == "LLM backend is not configured yet."


def test_non_streaming_and_streaming_share_same_service_result() -> None:
    ...
    assert non_streaming.json()["answer_text"] == "Answer"
    assert '"answer_text":"Answer"' in streaming.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_chat_service.py apps/api/app/tests/integration/test_chat_route.py -k "503 or share_same_service_result" -v`
Expected: FAIL until failure handling and shared-path checks are complete.

- [ ] **Step 3: Write the minimal implementation**

```python
# Keep one `_build_chat_service(request)` helper in the route module
# and use it from both endpoints so the tests can prove shared orchestration.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_chat_service.py apps/api/app/tests/integration/test_chat_route.py -k "503 or share_same_service_result" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/api/routes/chat.py apps/api/app/tests/unit/test_chat_service.py apps/api/app/tests/integration/test_chat_route.py
git commit -m "test: cover chat failure paths"
```

### Task 5: Run targeted regression and sync project memory

**Files:**
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`

- [ ] **Step 1: Run the targeted regression suite**

Run: `pytest apps/api/app/tests/unit/test_chat_service.py apps/api/app/tests/integration/test_chat_route.py apps/api/app/tests/unit/test_llm_backend.py apps/api/app/tests/unit/test_llm_runtime.py apps/api/app/tests/unit/test_context_builder.py apps/api/app/tests/unit/test_reranker.py apps/api/app/tests/unit/test_hybrid_retriever.py apps/api/app/tests/unit/test_query_router.py apps/api/app/tests/unit/test_search_runtime.py apps/api/app/tests/integration/test_runtime_auth_startup.py -v`
Expected: PASS

- [ ] **Step 2: Update project memory**

```markdown
- Record the shared `ChatService`, non-streaming `/chat`, and minimal streaming `/chat/stream` slice in `docs/uber-rag/PROJECT_STATE.md`.
- Mark `Implement chat API.` complete in `docs/uber-rag/TASKS.md`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md
git commit -m "docs: record phase 4 chat slice"
```
