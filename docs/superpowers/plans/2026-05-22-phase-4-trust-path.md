# Phase 4 Trust-Path Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the trust-critical Phase 4 backend path by adding citation resolution, sentence-level evidence verification, and fail-closed not-enough-evidence behavior to chat plus public verify/resolve endpoints.

**Architecture:** Extend the existing `ChatService` instead of replacing it. Keep retrieval, context building, and generation unchanged; add three small seams after generation: a metadata-only citation resolver, a deterministic sentence verifier, and a negative-answer policy that converts weakly supported output into the normalized insufficient-evidence response. Expose thin `/citations/resolve` and `/answers/verify` route adapters over the same core services.

**Tech Stack:** FastAPI, Pydantic v2, existing search/context/LLM seams, pytest, OpenAPI YAML, API_CONTRACT markdown

---

## File structure map

### New files

- `apps/api/app/schemas/citations.py` — request/response schemas for citation resolution and reusable normalized citation models
- `apps/api/app/schemas/verification.py` — verifier request/response schemas plus per-sentence support records
- `apps/api/app/services/citation_resolver.py` — metadata-only citation resolver service
- `apps/api/app/services/answer_verifier.py` — deterministic sentence verifier plus negative-answer policy helper
- `apps/api/app/api/routes/citations.py` — `POST /api/v1/citations/resolve`
- `apps/api/app/api/routes/answers_verify.py` — `POST /api/v1/answers/verify`
- `apps/api/app/tests/unit/test_citation_resolver.py` — unit coverage for citation resolution
- `apps/api/app/tests/unit/test_answer_verifier.py` — unit coverage for sentence verification and fail-closed policy
- `apps/api/app/tests/integration/test_citations_route.py` — integration coverage for citation resolve endpoint
- `apps/api/app/tests/integration/test_answers_verify_route.py` — integration coverage for verification endpoint

### Modified files

- `apps/api/app/schemas/chat.py` — extend `ChatResponse` with `citations` and `verification`
- `apps/api/app/services/chat_service.py` — run generation → verification → citation resolution → fail-closed policy; enrich audit details
- `apps/api/app/api/routes/chat.py` — inject the new trust-path services into `ChatService`
- `apps/api/app/api/router.py` — register new route modules
- `apps/api/app/tests/unit/test_chat_service.py` — update for verified answer path and post-generation not-enough-evidence path
- `apps/api/app/tests/integration/test_chat_route.py` — update JSON and SSE expectations for citations/verification behavior
- `apps/api/app/tests/unit/test_phase1_docs.py` — assert docs/OpenAPI truthfully describe the trust path
- `docs/uber-rag/API_CONTRACT.md` — document current truthful chat/citations/verification slice semantics
- `docs/uber-rag/api/openapi.yaml` — sync schemas and public endpoints with implemented behavior
- `docs/uber-rag/PROJECT_STATE.md` — record shipped Phase 4 trust-path slice and verification evidence
- `docs/uber-rag/TASKS.md` — mark the relevant Phase 4 items complete

---

### Task 1: Add citation and verification schemas

**Files:**
- Create: `apps/api/app/schemas/citations.py`
- Create: `apps/api/app/schemas/verification.py`
- Modify: `apps/api/app/schemas/chat.py`
- Test: `apps/api/app/tests/unit/test_chat_service.py`

- [ ] **Step 1: Write the failing schema expectations in the chat-service unit test**

```python
from app.schemas.citations import Citation, ResolveCitationsResponse
from app.schemas.verification import (
    VerificationSentenceResult,
    VerificationSummary,
)


def test_chat_service_returns_verified_answer_with_citations_and_summary(monkeypatch) -> None:
    monkeypatch.setattr("app.services.chat_service.write_audit_event", lambda **kwargs: None)

    class _FakeCitationResolver:
        def resolve(self, *, citation_ids, hits):
            return ResolveCitationsResponse(
                items=[
                    Citation(
                        citation_id="chunk-1",
                        document_id="doc-1",
                        document_title="Doc A",
                        chunk_id="chunk-1",
                        source_viewer_url="/api/v1/search/sources/chunk-1",
                    )
                ]
            )

    class _FakeAnswerVerifier:
        def verify(self, *, answer_text, context_payload):
            return VerificationSummary(
                status="supported",
                sentence_count=1,
                supported_sentence_count=1,
                unsupported_sentence_count=0,
                insufficient_evidence_sentence_count=0,
                sentences=[
                    VerificationSentenceResult(
                        sentence=answer_text,
                        status="supported",
                        citation_ids=["chunk-1"],
                    )
                ],
            )

    service = ChatService(
        search_service=_FakeSearchService([]),
        context_builder=_FakeContextBuilder([]),
        llm_backend=_FakeLlmBackend([]),
        citation_resolver=_FakeCitationResolver(),
        answer_verifier=_FakeAnswerVerifier(),
        max_context_characters=4000,
        max_context_blocks=None,
    )

    result = service.answer(context=_request_context(), payload=ChatRequest(question="What happened?", top_k=3))

    assert result.status == "answered"
    assert result.citations[0].citation_id == "chunk-1"
    assert result.citations[0].source_viewer_url == "/api/v1/search/sources/chunk-1"
    assert result.verification.status == "supported"
    assert result.verification.supported_sentence_count == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_chat_service.py::test_chat_service_returns_verified_answer_with_citations_and_summary -v`
Expected: FAIL because `ChatResponse` does not yet expose `citations` or `verification`, and `ChatService` does not accept resolver/verifier dependencies.

- [ ] **Step 3: Write the minimal schema implementation**

```python
# apps/api/app/schemas/citations.py
from pydantic import BaseModel, ConfigDict


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str
    document_id: str
    document_title: str
    chunk_id: str
    source_viewer_url: str
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = []


class ResolveCitationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citations: list[str]


class ResolveCitationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[Citation]
```

```python
# apps/api/app/schemas/verification.py
from typing import Literal

from pydantic import BaseModel, ConfigDict


class VerificationSentenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence: str
    status: Literal["supported", "unsupported", "insufficient_evidence"]
    citation_ids: list[str] = []


class VerificationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["supported", "unsupported", "insufficient_evidence"]
    sentence_count: int
    supported_sentence_count: int
    unsupported_sentence_count: int
    insufficient_evidence_sentence_count: int
    sentences: list[VerificationSentenceResult]


class VerifyAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer_text: str
    top_k: int = 5
```

```python
# apps/api/app/schemas/chat.py
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.citations import Citation
from app.schemas.verification import VerificationSummary


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str
    status: Literal["answered", "not_enough_evidence"]
    model_name: str | None = None
    provider_name: str | None = None
    context_block_count: int
    retrieval_hit_count: int
    usage: dict[str, int] | None = None
    citations: list[Citation] = []
    verification: VerificationSummary | None = None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_chat_service.py::test_chat_service_returns_verified_answer_with_citations_and_summary -v`
Expected: PASS once the schema surface exists and the test fakes can construct the new response shape.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/schemas/citations.py apps/api/app/schemas/verification.py apps/api/app/schemas/chat.py apps/api/app/tests/unit/test_chat_service.py
git commit -m "feat: add citation and verification schemas"
```

### Task 2: Implement the citation resolver service

**Files:**
- Create: `apps/api/app/services/citation_resolver.py`
- Test: `apps/api/app/tests/unit/test_citation_resolver.py`

- [ ] **Step 1: Write the failing resolver tests**

```python
from app.schemas.search import SearchHitResponse
from app.services.citation_resolver import CitationResolver


def test_citation_resolver_returns_resolvable_citations_in_hit_order() -> None:
    resolver = CitationResolver()
    hits = [
        SearchHitResponse(
            document_id="doc-1",
            document_title="Doc A",
            source_type="loose_document",
            chunk_id="chunk-1",
            citation_id="chunk-1",
            source_viewer_url="/api/v1/search/sources/chunk-1",
            route="semantic",
            score=0.9,
            text="Alpha evidence",
            page_start=2,
            page_end=2,
            heading_path=["A"],
        )
    ]

    result = resolver.resolve(citation_ids=["chunk-1"], hits=hits)

    assert [item.citation_id for item in result.items] == ["chunk-1"]
    assert result.items[0].document_title == "Doc A"


def test_citation_resolver_drops_unresolvable_ids_without_emitting_broken_urls() -> None:
    resolver = CitationResolver()
    result = resolver.resolve(citation_ids=["missing"], hits=[])

    assert result.items == []
```

- [ ] **Step 2: Run the resolver tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_citation_resolver.py -v`
Expected: FAIL because the resolver service does not exist yet.

- [ ] **Step 3: Write the minimal resolver implementation**

```python
from app.schemas.citations import Citation, ResolveCitationsResponse


class CitationResolver:
    def resolve(self, *, citation_ids: list[str], hits: list) -> ResolveCitationsResponse:
        by_id = {
            hit.citation_id: hit
            for hit in hits
            if hit.citation_id is not None and hit.chunk_id is not None and hit.source_viewer_url is not None
        }
        items: list[Citation] = []
        for citation_id in citation_ids:
            hit = by_id.get(citation_id)
            if hit is None:
                continue
            items.append(
                Citation(
                    citation_id=citation_id,
                    document_id=hit.document_id,
                    document_title=hit.document_title,
                    chunk_id=hit.chunk_id,
                    source_viewer_url=hit.source_viewer_url,
                    page_start=hit.page_start,
                    page_end=hit.page_end,
                    heading_path=hit.heading_path,
                )
            )
        return ResolveCitationsResponse(items=items)
```

- [ ] **Step 4: Run the resolver tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_citation_resolver.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/citation_resolver.py apps/api/app/tests/unit/test_citation_resolver.py
git commit -m "feat: add citation resolver service"
```

### Task 3: Implement sentence verification and fail-closed chat policy

**Files:**
- Create: `apps/api/app/services/answer_verifier.py`
- Modify: `apps/api/app/services/chat_service.py`
- Modify: `apps/api/app/tests/unit/test_chat_service.py`
- Test: `apps/api/app/tests/unit/test_answer_verifier.py`

- [ ] **Step 1: Write the failing verifier and fail-closed chat tests**

```python
from app.schemas.context import ContextBlock, ContextPayload
from app.schemas.citations import ResolveCitationsResponse
from app.services.answer_verifier import AnswerVerifier


def test_answer_verifier_marks_sentence_supported_when_overlap_exists() -> None:
    verifier = AnswerVerifier()
    summary = verifier.verify(
        answer_text="Alpha evidence proves the answer.",
        context_payload=ContextPayload(
            blocks=[
                ContextBlock(
                    text="Alpha evidence proves the answer.",
                    document_id="doc-1",
                    document_title="Doc A",
                    chunk_id="chunk-1",
                    citation_id="chunk-1",
                    page_start=1,
                    page_end=1,
                    heading_path=["A"],
                    rank=1,
                )
            ],
            block_count=1,
            total_characters=32,
            truncated=False,
        ),
    )

    assert summary.status == "supported"
    assert summary.supported_sentence_count == 1
    assert summary.sentences[0].citation_ids == ["chunk-1"]


def test_chat_service_returns_not_enough_evidence_when_verifier_rejects_generated_answer(monkeypatch) -> None:
    monkeypatch.setattr("app.services.chat_service.write_audit_event", lambda **kwargs: None)

    class _FakeUnsupportedLlmBackend:
        def __init__(self, call_log: list[str]) -> None:
            self.call_log = call_log

        def generate(self, request):
            self.call_log.append(f"llm:{request.question}:{request.context_payload.block_count}")
            return GenerateAnswerResponse(
                answer_text="This claim is not in the evidence.",
                model_name="stub-model",
                provider_name="stub",
                usage={"total_tokens": 12},
            )

    class _FakeCitationResolver:
        def resolve(self, *, citation_ids, hits):
            return ResolveCitationsResponse(items=[])

    service = ChatService(
        search_service=_FakeSearchService([]),
        context_builder=_FakeContextBuilder([]),
        llm_backend=_FakeUnsupportedLlmBackend([]),
        citation_resolver=_FakeCitationResolver(),
        answer_verifier=AnswerVerifier(),
        max_context_characters=4000,
        max_context_blocks=None,
    )

    result = service.answer(context=_request_context(), payload=ChatRequest(question="What happened?", top_k=3))

    assert result.status == "not_enough_evidence"
    assert result.answer_text == NOT_ENOUGH_EVIDENCE_MESSAGE
    assert result.citations == []
    assert result.verification is not None
    assert result.verification.status == "unsupported"
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_answer_verifier.py apps/api/app/tests/unit/test_chat_service.py -k "supported_when_overlap_exists or verifier_rejects_generated_answer" -v`
Expected: FAIL because the verifier service and post-generation fail-closed policy do not exist yet.

- [ ] **Step 3: Write the minimal verifier and chat integration**

```python
# apps/api/app/services/answer_verifier.py
import re

from app.schemas.verification import VerificationSentenceResult, VerificationSummary


class AnswerVerifier:
    def verify(self, *, answer_text: str, context_payload) -> VerificationSummary:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", answer_text) if part.strip()]
        results: list[VerificationSentenceResult] = []
        for sentence in sentences:
            normalized_sentence = sentence.casefold()
            matched_citation_ids = [
                block.citation_id
                for block in context_payload.blocks
                if block.citation_id and normalized_sentence in block.text.casefold()
            ]
            if matched_citation_ids:
                status = "supported"
            elif context_payload.block_count == 0:
                status = "insufficient_evidence"
            else:
                status = "unsupported"
            results.append(
                VerificationSentenceResult(
                    sentence=sentence,
                    status=status,
                    citation_ids=matched_citation_ids,
                )
            )
        supported = sum(1 for item in results if item.status == "supported")
        unsupported = sum(1 for item in results if item.status == "unsupported")
        insufficient = sum(1 for item in results if item.status == "insufficient_evidence")
        overall = "supported" if results and unsupported == 0 and insufficient == 0 else "unsupported"
        return VerificationSummary(
            status=overall,
            sentence_count=len(results),
            supported_sentence_count=supported,
            unsupported_sentence_count=unsupported,
            insufficient_evidence_sentence_count=insufficient,
            sentences=results,
        )
```

```python
# apps/api/app/services/chat_service.py
verification = self._answer_verifier.verify(
    answer_text=generation_response.answer_text,
    context_payload=context_payload,
)
if verification.status != "supported":
    result = ChatResponse(
        answer_text=NOT_ENOUGH_EVIDENCE_MESSAGE,
        status="not_enough_evidence",
        model_name=None,
        provider_name=None,
        context_block_count=context_payload.block_count,
        retrieval_hit_count=search_response.total,
        usage=None,
        citations=[],
        verification=verification,
    )
    self._write_chat_audit_event(
        context=context,
        payload=payload,
        search_response=search_response,
        context_payload=context_payload,
        result=result,
        generation_response=generation_response,
        delivery_mode=delivery_mode,
        verification=verification,
        citations=[],
    )
    return result

citation_ids = [citation_id for sentence in verification.sentences for citation_id in sentence.citation_ids]
citations = self._citation_resolver.resolve(citation_ids=citation_ids, hits=search_response.items).items
result = ChatResponse(
    answer_text=generation_response.answer_text,
    status="answered",
    model_name=generation_response.model_name,
    provider_name=generation_response.provider_name,
    context_block_count=context_payload.block_count,
    retrieval_hit_count=search_response.total,
    usage=generation_response.usage,
    citations=citations,
    verification=verification,
)
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_answer_verifier.py apps/api/app/tests/unit/test_chat_service.py -k "supported_when_overlap_exists or verifier_rejects_generated_answer or verified_answer_with_citations" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/answer_verifier.py apps/api/app/services/chat_service.py apps/api/app/tests/unit/test_answer_verifier.py apps/api/app/tests/unit/test_chat_service.py
git commit -m "feat: verify chat answers against evidence"
```

### Task 4: Expose `/citations/resolve` and `/answers/verify` through thin routes

**Files:**
- Create: `apps/api/app/api/routes/citations.py`
- Create: `apps/api/app/api/routes/answers_verify.py`
- Modify: `apps/api/app/api/router.py`
- Test: `apps/api/app/tests/integration/test_citations_route.py`
- Test: `apps/api/app/tests/integration/test_answers_verify_route.py`

- [ ] **Step 1: Write the failing route tests**

```python
def test_citations_resolve_route_returns_only_resolvable_authorized_citations() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/citations/resolve",
            json={"citations": ["chunk-1", "missing"]},
            headers=_dev_auth_headers(scopes=["documents:read"]),
        )

    assert response.status_code == 200
    assert [item["citation_id"] for item in response.json()["items"]] == ["chunk-1"]


def test_answers_verify_route_returns_sentence_support_summary() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/answers/verify",
            json={
                "question": "What happened?",
                "answer_text": "Alpha evidence proves the answer.",
                "top_k": 3,
            },
            headers=_dev_auth_headers(scopes=["documents:read"]),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "supported"
    assert response.json()["supported_sentence_count"] == 1
```

- [ ] **Step 2: Run the route tests to verify they fail**

Run: `pytest apps/api/app/tests/integration/test_citations_route.py apps/api/app/tests/integration/test_answers_verify_route.py -v`
Expected: FAIL because the routes are not registered yet.

- [ ] **Step 3: Write the minimal route implementation**

```python
# apps/api/app/api/routes/citations.py
from fastapi import APIRouter, Depends, Request

from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.schemas.search import SearchRequest
from app.schemas.citations import ResolveCitationsRequest, ResolveCitationsResponse
from app.services.citation_resolver import CitationResolver
from app.services.retrieval.search_service import SearchService

router = APIRouter()


@router.post("/resolve", response_model=ResolveCitationsResponse)
def resolve_citations_route(
    request: Request,
    payload: ResolveCitationsRequest,
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> ResolveCitationsResponse:
    search_service = SearchService(retriever=request.app.state.search_retriever)
    search_response = search_service.search(
        context=context,
        payload=SearchRequest(query=" ".join(payload.citations), top_k=max(len(payload.citations), 1)),
    )
    return CitationResolver().resolve(citation_ids=payload.citations, hits=search_response.items)
```

```python
# apps/api/app/api/routes/answers_verify.py
from fastapi import APIRouter, Depends, Request

from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.schemas.context import BuildContextRequest
from app.schemas.search import SearchRequest
from app.schemas.verification import VerifyAnswerRequest, VerificationSummary
from app.services.answer_verifier import AnswerVerifier
from app.services.context_builder import DefaultContextBuilder
from app.services.retrieval.base import RetrievalHit
from app.services.retrieval.search_service import SearchService

router = APIRouter()


@router.post("/verify", response_model=VerificationSummary)
def verify_answer_route(
    request: Request,
    payload: VerifyAnswerRequest,
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> VerificationSummary:
    search_response = SearchService(retriever=request.app.state.search_retriever).search(
        context=context,
        payload=SearchRequest(query=payload.question, top_k=payload.top_k),
    )
    context_payload = DefaultContextBuilder().build(
        BuildContextRequest(
            hits=[
                RetrievalHit(
                    document_id=item.document_id,
                    chunk_id=item.chunk_id,
                    score=item.score,
                    text=item.text,
                    page_start=item.page_start,
                    page_end=item.page_end,
                    heading_path=item.heading_path,
                    route=item.route,
                )
                for item in search_response.items
            ],
            document_titles={item.document_id: item.document_title for item in search_response.items},
            max_characters=request.app.state.settings.context_builder_max_characters,
            max_blocks=request.app.state.settings.context_builder_max_blocks,
        )
    )
    return AnswerVerifier().verify(answer_text=payload.answer_text, context_payload=context_payload)
```

```python
# apps/api/app/api/router.py
from app.api.routes.answers_verify import router as answers_verify_router
from app.api.routes.citations import router as citations_router

api_router.include_router(citations_router, prefix="/citations", tags=["citations"])
api_router.include_router(answers_verify_router, prefix="/answers", tags=["answers"])
```

- [ ] **Step 4: Run the route tests to verify they pass**

Run: `pytest apps/api/app/tests/integration/test_citations_route.py apps/api/app/tests/integration/test_answers_verify_route.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/api/routes/citations.py apps/api/app/api/routes/answers_verify.py apps/api/app/api/router.py apps/api/app/tests/integration/test_citations_route.py apps/api/app/tests/integration/test_answers_verify_route.py
git commit -m "feat: add citation resolve and answer verify routes"
```

### Task 5: Update chat transport, docs, OpenAPI, and regression coverage

**Files:**
- Modify: `apps/api/app/api/routes/chat.py`
- Modify: `apps/api/app/tests/integration/test_chat_route.py`
- Modify: `apps/api/app/tests/unit/test_phase1_docs.py`
- Modify: `docs/uber-rag/API_CONTRACT.md`
- Modify: `docs/uber-rag/api/openapi.yaml`
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`

- [ ] **Step 1: Write the failing integration and docs tests**

```python
def test_chat_route_returns_verified_payload_with_citations() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={"question": "What happened?", "top_k": 3},
            headers=_dev_auth_headers(scopes=["documents:read"]),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["citations"][0]["citation_id"] == "chunk-1"
    assert body["verification"]["status"] == "supported"


def test_chat_stream_route_emits_verified_answer_payload() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={"question": "What happened?", "top_k": 3},
            headers=_dev_auth_headers(scopes=["documents:read"]),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"citations":[{"citation_id":"chunk-1"' in response.text
    assert '"verification":{"status":"supported"' in response.text


def test_phase4_trust_path_openapi_and_contract_are_truthful() -> None:
    api_contract = Path("docs/uber-rag/API_CONTRACT.md").read_text()
    openapi_text = Path("docs/uber-rag/api/openapi.yaml").read_text()

    assert "POST   /api/v1/citations/resolve" in api_contract
    assert "POST   /api/v1/answers/verify" in api_contract
    assert "citations:" in openapi_text.split("    ChatResponse:")[1].split("    Citation:")[0]
    assert "verification:" in openapi_text.split("    ChatResponse:")[1].split("    Citation:")[0]
    assert "/citations/resolve:" in openapi_text
    assert "/answers/verify:" in openapi_text
```

- [ ] **Step 2: Run the targeted regression and docs tests to verify they fail**

Run: `pytest apps/api/app/tests/integration/test_chat_route.py apps/api/app/tests/unit/test_phase1_docs.py -k "verified_payload or trust_path_openapi" -v`
Expected: FAIL because chat transport, contract docs, and OpenAPI do not yet describe the new trust path.

- [ ] **Step 3: Write the minimal implementation and documentation updates**

```python
# apps/api/app/api/routes/chat.py
return ChatService(
    search_service=SearchService(retriever=retriever),
    context_builder=DefaultContextBuilder(),
    llm_backend=llm_backend,
    citation_resolver=CitationResolver(),
    answer_verifier=AnswerVerifier(),
    max_context_characters=settings.context_builder_max_characters,
    max_context_blocks=settings.context_builder_max_blocks,
)
```

```yaml
# docs/uber-rag/api/openapi.yaml
    ChatResponse:
      type: object
      additionalProperties: false
      required: [answer_text, status, context_block_count, retrieval_hit_count, citations]
      properties:
        answer_text: { type: string }
        status:
          type: string
          enum: [answered, not_enough_evidence]
        citations:
          type: array
          items: { $ref: "#/components/schemas/Citation" }
        verification:
          allOf:
            - $ref: "#/components/schemas/VerificationSummary"
          nullable: true
```

```markdown
# docs/uber-rag/API_CONTRACT.md
- `POST /api/v1/chat` now runs post-generation sentence verification before returning `status=answered`.
- If verification shows insufficient support, the service returns `status=not_enough_evidence` and omits unsupported generated text.
- `POST /api/v1/citations/resolve` returns only resolvable authorized citations.
- `POST /api/v1/answers/verify` returns deterministic sentence support summaries over ACL-safe retrieved evidence.
```

- [ ] **Step 4: Run the full targeted verification suite**

Run: `pytest apps/api/app/tests/unit/test_citation_resolver.py apps/api/app/tests/unit/test_answer_verifier.py apps/api/app/tests/unit/test_chat_service.py apps/api/app/tests/integration/test_citations_route.py apps/api/app/tests/integration/test_answers_verify_route.py apps/api/app/tests/integration/test_chat_route.py apps/api/app/tests/unit/test_phase1_docs.py -v`
Expected: PASS

- [ ] **Step 5: Update project memory and commit**

```bash
git add apps/api/app/api/routes/chat.py apps/api/app/tests/integration/test_chat_route.py apps/api/app/tests/unit/test_phase1_docs.py docs/uber-rag/API_CONTRACT.md docs/uber-rag/api/openapi.yaml docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md
git commit -m "feat: complete phase 4 trust path"
```

## Self-review checklist

- Spec coverage: citation resolver, verifier, fail-closed behavior, public routes, docs truthfulness, and project-memory updates all map to tasks above.
- Placeholder scan: no `TODO`/`TBD` steps remain; every task has explicit files, commands, and code examples.
- Type consistency: `Citation`, `VerificationSummary`, and extended `ChatResponse` names are used consistently across service, route, and docs tasks.
