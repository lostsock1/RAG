from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.request_context import RequestContext
from app.schemas.chat import ChatRequest
from app.schemas.context import ContextPayload
from app.schemas.generation import GenerateAnswerResponse
from app.schemas.search import SearchHitResponse, SearchResponse
from app.services.chat_service import ChatService, NOT_ENOUGH_EVIDENCE_MESSAGE
from app.schemas.citations import Citation, ResolveCitationsResponse
from app.schemas.verification import VerificationSentenceResult, VerificationSummary
from app.services.answer_verifier import AnswerVerifier


class _FakeSearchService:
    def __init__(self, call_log: list[str], response: SearchResponse | None = None) -> None:
        self.call_log = call_log
        self.response = response

    def search(self, *, context: RequestContext, payload) -> SearchResponse:
        self.call_log.append(f"search:{payload.query}:{payload.top_k}:{context.user_id}")
        if self.response is not None:
            return self.response
        return SearchResponse(
            items=[
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
                    page_start=1,
                    page_end=1,
                    heading_path=["A"],
                )
            ],
            total=1,
        )


class _FakeContextBuilder:
    def __init__(self, call_log: list[str], payload: ContextPayload | None = None) -> None:
        self.call_log = call_log
        self.payload = payload

    def build(self, request) -> ContextPayload:
        self.call_log.append(f"context:{len(request.hits)}:{request.max_characters}:{request.max_blocks}")
        if self.payload is not None:
            return self.payload
        return ContextPayload(
            blocks=[],
            block_count=1,
            total_characters=14,
            truncated=False,
        )


class _FakeLlmBackend:
    def __init__(self, call_log: list[str]) -> None:
        self.call_log = call_log

    def generate(self, request) -> GenerateAnswerResponse:
        self.call_log.append(f"llm:{request.question}:{request.context_payload.block_count}")
        return GenerateAnswerResponse(
            answer_text="Answer",
            model_name="stub-model",
            provider_name="stub",
            usage={"total_tokens": 12},
        )


class _FakeCitationResolver:
    def __init__(self, call_log: list[str]) -> None:
        self.call_log = call_log

    def resolve(self, *, citation_ids, hits):
        self.call_log.append(f"resolve:{citation_ids}")
        return ResolveCitationsResponse(
            items=[
                Citation(
                    citation_id=cid,
                    document_id="doc-1",
                    document_title="Doc A",
                    chunk_id=cid,
                    source_viewer_url=f"/api/v1/search/sources/{cid}",
                )
                for cid in citation_ids
            ]
        )


class _FakeAnswerVerifier:
    def __init__(self, call_log: list[str]) -> None:
        self.call_log = call_log

    def verify(self, *, answer_text, context_payload):
        self.call_log.append(f"verify:{context_payload.block_count}")
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


class _FakeUnsupportedLlmBackend:
    def __init__(self, call_log: list[str]) -> None:
        self.call_log = call_log

    def generate(self, request) -> GenerateAnswerResponse:
        self.call_log.append(f"llm:{request.question}:{request.context_payload.block_count}")
        return GenerateAnswerResponse(
            answer_text="This claim is not in the evidence at all.",
            model_name="stub-model",
            provider_name="stub",
            usage={"total_tokens": 12},
        )


def _request_context() -> RequestContext:
    return RequestContext(
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        group_ids=[],
        roles=["reader"],
        scopes=["documents:read"],
    )


def test_chat_service_calls_search_context_builder_and_llm_in_order(monkeypatch) -> None:
    monkeypatch.setattr("app.services.chat_service.write_audit_event", lambda **kwargs: None)
    call_log: list[str] = []
    service = ChatService(
        search_service=_FakeSearchService(call_log),
        context_builder=_FakeContextBuilder(call_log),
        llm_backend=_FakeLlmBackend(call_log),
        citation_resolver=_FakeCitationResolver(call_log),
        answer_verifier=_FakeAnswerVerifier(call_log),
        max_context_characters=4000,
        max_context_blocks=None,
    )

    result = service.answer(
        context=_request_context(),
        payload=ChatRequest(question="What happened?", top_k=3),
    )

    assert result.answer_text == "Answer"
    assert result.status == "answered"
    assert result.provider_name == "stub"
    assert result.context_block_count == 1
    assert result.retrieval_hit_count == 1
    assert result.usage == {"total_tokens": 12}
    assert call_log == [
        "search:What happened?:3:00000000-0000-0000-0000-000000000002",
        "context:1:4000:None",
        "llm:What happened?:1",
        "verify:1",
        "resolve:['chunk-1']",
    ]


def test_chat_service_returns_not_enough_evidence_without_calling_llm_when_search_has_no_hits(monkeypatch) -> None:
    call_log: list[str] = []
    audit_calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.chat_service.write_audit_event",
        lambda **kwargs: audit_calls.append(kwargs),
    )
    service = ChatService(
        search_service=_FakeSearchService(call_log, response=SearchResponse(items=[], total=0)),
        context_builder=_FakeContextBuilder(call_log, payload=ContextPayload(blocks=[], block_count=0, total_characters=0)),
        llm_backend=_FakeLlmBackend(call_log),
        citation_resolver=_FakeCitationResolver(call_log),
        answer_verifier=_FakeAnswerVerifier(call_log),
        max_context_characters=4000,
        max_context_blocks=None,
    )

    result = service.answer(
        context=_request_context(),
        payload=ChatRequest(question="What happened?", top_k=3),
    )

    assert result.status == "not_enough_evidence"
    assert result.answer_text == "I do not have enough permitted source evidence to answer that yet."
    assert result.model_name is None
    assert result.provider_name is None
    assert result.context_block_count == 0
    assert result.retrieval_hit_count == 0
    assert result.usage is None
    assert call_log == [
        "search:What happened?:3:00000000-0000-0000-0000-000000000002",
        "context:0:4000:None",
    ]
    assert audit_calls[0]["action"] == "chat.answer"
    assert audit_calls[0]["details"]["outcome_status"] == "not_enough_evidence"
    assert audit_calls[0]["details"]["llm_invoked"] is False
    assert "question" not in audit_calls[0]["details"]


def test_chat_service_returns_not_enough_evidence_without_calling_llm_when_context_builder_has_no_blocks(monkeypatch) -> None:
    call_log: list[str] = []
    audit_calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.chat_service.write_audit_event",
        lambda **kwargs: audit_calls.append(kwargs),
    )
    service = ChatService(
        search_service=_FakeSearchService(call_log),
        context_builder=_FakeContextBuilder(call_log, payload=ContextPayload(blocks=[], block_count=0, total_characters=0)),
        llm_backend=_FakeLlmBackend(call_log),
        citation_resolver=_FakeCitationResolver(call_log),
        answer_verifier=_FakeAnswerVerifier(call_log),
        max_context_characters=4000,
        max_context_blocks=None,
    )

    result = service.answer(
        context=_request_context(),
        payload=ChatRequest(question="What happened?", top_k=3),
    )

    assert result.status == "not_enough_evidence"
    assert result.model_name is None
    assert result.provider_name is None
    assert call_log == [
        "search:What happened?:3:00000000-0000-0000-0000-000000000002",
        "context:1:4000:None",
    ]
    assert audit_calls[0]["details"]["retrieval_hit_count"] == 1
    assert audit_calls[0]["details"]["context_block_count"] == 0


def test_chat_service_writes_non_sensitive_chat_audit_for_answered_path(monkeypatch) -> None:
    call_log: list[str] = []
    audit_calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.chat_service.write_audit_event",
        lambda **kwargs: audit_calls.append(kwargs),
    )
    service = ChatService(
        search_service=_FakeSearchService(call_log),
        context_builder=_FakeContextBuilder(call_log),
        llm_backend=_FakeLlmBackend(call_log),
        citation_resolver=_FakeCitationResolver(call_log),
        answer_verifier=_FakeAnswerVerifier(call_log),
        max_context_characters=4000,
        max_context_blocks=None,
    )

    result = service.answer(
        context=_request_context(),
        payload=ChatRequest(question="What happened?", top_k=3),
        delivery_mode="streaming",
    )

    assert result.status == "answered"
    assert audit_calls[0]["action"] == "chat.answer"
    assert audit_calls[0]["details"] == {
        "query_sha256": "c4dc542b511fd74f401665a02dd5a20cf41cebd16daa6a7f78ddfbcce88239fe",
        "query_length": 14,
        "top_k": 3,
        "delivery_mode": "streaming",
        "filters_applied": ["acl"],
        "retrieved_document_ids": ["doc-1"],
        "retrieval_hit_count": 1,
        "context_block_count": 1,
        "citations_returned": 1,
        "llm_invoked": True,
        "model_name": "stub-model",
        "provider_name": "stub",
        "verification_status": "supported",
        "outcome_status": "answered",
    }


def test_chat_service_returns_verified_answer_with_citations_and_summary(monkeypatch) -> None:
    monkeypatch.setattr("app.services.chat_service.write_audit_event", lambda **kwargs: None)

    class _LocalFakeCitationResolver:
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

    class _LocalFakeAnswerVerifier:
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
        citation_resolver=_LocalFakeCitationResolver(),
        answer_verifier=_LocalFakeAnswerVerifier(),
        max_context_characters=4000,
        max_context_blocks=None,
    )

    result = service.answer(context=_request_context(), payload=ChatRequest(question="What happened?", top_k=3))

    assert result.status == "answered"
    assert result.citations[0].citation_id == "chunk-1"
    assert result.citations[0].source_viewer_url == "/api/v1/search/sources/chunk-1"
    assert result.verification is not None
    assert result.verification.status == "supported"
    assert result.verification.supported_sentence_count == 1


def test_chat_service_returns_not_enough_evidence_when_verifier_rejects_generated_answer(monkeypatch) -> None:
    call_log: list[str] = []
    audit_calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.chat_service.write_audit_event",
        lambda **kwargs: audit_calls.append(kwargs),
    )
    service = ChatService(
        search_service=_FakeSearchService(call_log),
        context_builder=_FakeContextBuilder(call_log),
        llm_backend=_FakeUnsupportedLlmBackend(call_log),
        citation_resolver=_FakeCitationResolver(call_log),
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
    assert audit_calls[0]["details"]["verification_status"] == "unsupported"
    assert audit_calls[0]["details"]["llm_invoked"] is True
