"""Integration test: real token-level streaming via /chat/stream."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import anyio
import pytest

from app.core.request_context import RequestContext
from app.schemas.chat import ChatRequest
from app.schemas.generation import TokenEvent
from app.schemas.search import SearchResponse, SearchHitResponse
from app.schemas.verification import VerificationSummary, VerificationSentenceResult
from app.services.answer_verifier import AnswerVerifier
from app.services.citation_resolver import CitationResolver
from app.services.chat_service import ChatService
from app.services.context_builder import DefaultContextBuilder


def _make_context():
    return RequestContext(
        tenant_id="00000000-0000-0000-0000-000000000000",
        user_id="00000000-0000-0000-0000-000000000001",
        group_ids=["test-group"],
        roles=["test"],
        scopes=["documents:read"],
    )


class _StubStreamingLlm:
    """LLM backend that streams tokens with delays."""

    def generate(self, request):
        from unittest.mock import MagicMock
        return MagicMock(answer_text="Generated answer", model_name="stub", provider_name="stub", usage=None)

    async def generate_stream(self, request):
        tokens = ["The ", "second ", "law ", "of ", "thermodynamics ", "states ", "that ", "entropy ", "never ", "decreases."]
        for token in tokens:
            await anyio.sleep(0.05)
            yield TokenEvent(text=token, is_final=False)
        yield TokenEvent(text="", is_final=True, usage={"total_tokens": len(tokens)})


class _StubSearchWithHits:
    def search(self, *, context, payload):
        return SearchResponse(
            items=[
                SearchHitResponse(
                    document_id="doc-1",
                    document_title="Physics Textbook",
                    source_type="book",
                    chunk_id="chunk-1",
                    citation_id="chunk-1",
                    source_viewer_url="/api/v1/search/sources/chunk-1",
                    route="dense",
                    score=0.95,
                    text="The second law of thermodynamics states that entropy of an isolated system can never decrease over time.",
                )
            ],
            total=1,
        )


class _PassThroughVerifier:
    """Verifier that always marks every sentence as supported with citation_id=chunk-1."""

    def verify(self, *, answer_text, context_payload):
        import re
        sentences = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+", answer_text)
            if part.strip()
        ]
        results = [
            VerificationSentenceResult(sentence=s, status="supported", citation_ids=["chunk-1"])
            for s in sentences
        ]
        return VerificationSummary(
            status="supported",
            sentence_count=len(results),
            supported_sentence_count=len(results),
            unsupported_sentence_count=0,
            insufficient_evidence_sentence_count=0,
            sentences=results,
        )


class _UnsupportedVerifier:
    """Verifier that always returns unsupported — used to prove no tokens are emitted."""

    def verify(self, *, answer_text, context_payload):
        return VerificationSummary(
            status="unsupported",
            sentence_count=1,
            supported_sentence_count=0,
            unsupported_sentence_count=1,
            insufficient_evidence_sentence_count=0,
            sentences=[
                VerificationSentenceResult(
                    sentence=answer_text, status="unsupported", citation_ids=[]
                )
            ],
        )


class TestChatStreamFirstToken:
    """Verify first token arrives before LLM finishes generating all tokens."""

    @pytest.fixture(autouse=True)
    def _disable_audit(self, monkeypatch):
        monkeypatch.setattr("app.services.chat_service.write_audit_event", lambda **kwargs: None)

    @pytest.mark.anyio
    async def test_first_token_arrives_before_completion(self):
        """First token event must arrive before the done event (tokens are buffered until verification passes)."""
        chat_service = ChatService(
            search_service=_StubSearchWithHits(),
            context_builder=DefaultContextBuilder(),
            llm_backend=_StubStreamingLlm(),
            citation_resolver=CitationResolver(),
            answer_verifier=_PassThroughVerifier(),
            max_context_characters=4000,
            max_context_blocks=None,
        )

        events = []
        first_token_time = None
        completion_time = None

        async for event in chat_service.answer_stream(
            context=_make_context(),
            payload=ChatRequest(question="What is the second law of thermodynamics?"),
        ):
            events.append(event)
            if event["type"] == "token" and first_token_time is None:
                first_token_time = time.perf_counter()
            if event["type"] == "done":
                completion_time = time.perf_counter()

        # Must have received events
        assert len(events) > 0

        # Must have token events
        token_events = [e for e in events if e["type"] == "token"]
        assert len(token_events) > 0, "No token events received"

        # First token must arrive before completion
        assert first_token_time is not None
        assert completion_time is not None
        assert first_token_time < completion_time, (
            f"First token at {first_token_time:.3f}s must be before completion at {completion_time:.3f}s"
        )

    @pytest.mark.anyio
    async def test_event_sequence_is_correct(self):
        """Event sequence must be: retrieval -> verification(supported) -> token+ -> citations -> final -> done."""
        chat_service = ChatService(
            search_service=_StubSearchWithHits(),
            context_builder=DefaultContextBuilder(),
            llm_backend=_StubStreamingLlm(),
            citation_resolver=CitationResolver(),
            answer_verifier=_PassThroughVerifier(),
            max_context_characters=4000,
            max_context_blocks=None,
        )

        events = []
        async for event in chat_service.answer_stream(
            context=_make_context(),
            payload=ChatRequest(question="What is the second law of thermodynamics?"),
        ):
            events.append(event)

        event_types = [e["type"] for e in events]

        # Must start with retrieval
        assert event_types[0] == "retrieval"

        # Verification must come before any tokens
        assert "verification" in event_types
        assert "token" in event_types
        verification_idx = event_types.index("verification")
        first_token_idx = event_types.index("token")
        assert verification_idx < first_token_idx, (
            f"verification at {verification_idx} must precede first token at {first_token_idx}"
        )

        # Must end with done
        assert event_types[-1] == "done"

        # Must have final before done
        assert event_types[-2] == "final"

    @pytest.mark.anyio
    async def test_empty_corpus_returns_not_enough_evidence(self):
        """With no search hits, stream should return not_enough_evidence immediately."""
        class _EmptySearch:
            def search(self, *, context, payload):
                return SearchResponse(items=[], total=0)

        chat_service = ChatService(
            search_service=_EmptySearch(),
            context_builder=DefaultContextBuilder(),
            llm_backend=_StubStreamingLlm(),
            citation_resolver=CitationResolver(),
            answer_verifier=_PassThroughVerifier(),
            max_context_characters=4000,
            max_context_blocks=None,
        )

        events = []
        async for event in chat_service.answer_stream(
            context=_make_context(),
            payload=ChatRequest(question="What is the second law?"),
        ):
            events.append(event)

        event_types = [e["type"] for e in events]

        # Should be: retrieval -> final (not_enough_evidence) -> done
        assert event_types == ["retrieval", "final", "done"]
        assert events[1]["data"]["status"] == "not_enough_evidence"

    @pytest.mark.anyio
    async def test_reconstructed_answer_matches_streamed_tokens(self):
        """Concatenating all token events must produce the full answer text."""
        chat_service = ChatService(
            search_service=_StubSearchWithHits(),
            context_builder=DefaultContextBuilder(),
            llm_backend=_StubStreamingLlm(),
            citation_resolver=CitationResolver(),
            answer_verifier=_PassThroughVerifier(),
            max_context_characters=4000,
            max_context_blocks=None,
        )

        events = []
        async for event in chat_service.answer_stream(
            context=_make_context(),
            payload=ChatRequest(question="What is the second law of thermodynamics?"),
        ):
            events.append(event)

        token_texts = [e["data"]["text"] for e in events if e["type"] == "token"]
        streamed_answer = "".join(token_texts)

        final_events = [e for e in events if e["type"] == "final"]
        assert len(final_events) == 1
        assert final_events[0]["data"]["answer_text"] == streamed_answer
        assert final_events[0]["data"]["status"] == "answered"

    @pytest.mark.anyio
    async def test_verification_supported_includes_citations(self):
        """When verification passes, citations event must appear after verification and before final."""
        chat_service = ChatService(
            search_service=_StubSearchWithHits(),
            context_builder=DefaultContextBuilder(),
            llm_backend=_StubStreamingLlm(),
            citation_resolver=CitationResolver(),
            answer_verifier=_PassThroughVerifier(),
            max_context_characters=4000,
            max_context_blocks=None,
        )

        events = []
        async for event in chat_service.answer_stream(
            context=_make_context(),
            payload=ChatRequest(question="What is the second law of thermodynamics?"),
        ):
            events.append(event)

        event_types = [e["type"] for e in events]

        # Must have verification, citations, and final in correct order
        assert "verification" in event_types
        assert "citations" in event_types

        verification_idx = event_types.index("verification")
        citations_idx = event_types.index("citations")
        final_idx = event_types.index("final")

        assert verification_idx < citations_idx < final_idx

        # Verification must be supported
        verification_event = events[verification_idx]
        assert verification_event["data"]["status"] == "supported"

    @pytest.mark.anyio
    async def test_unsupported_answer_emits_no_tokens(self):
        """When verification fails, zero token events must be emitted — evidence discipline."""
        chat_service = ChatService(
            search_service=_StubSearchWithHits(),
            context_builder=DefaultContextBuilder(),
            llm_backend=_StubStreamingLlm(),
            citation_resolver=CitationResolver(),
            answer_verifier=_UnsupportedVerifier(),
            max_context_characters=4000,
            max_context_blocks=None,
        )

        events = []
        async for event in chat_service.answer_stream(
            context=_make_context(),
            payload=ChatRequest(question="What is the second law of thermodynamics?"),
        ):
            events.append(event)

        event_types = [e["type"] for e in events]

        # No token events must be emitted
        token_events = [e for e in events if e["type"] == "token"]
        assert token_events == [], (
            f"Expected zero token events when verification fails, got {len(token_events)}"
        )

        # Sequence must be: retrieval -> verification(unsupported) -> final(not_enough_evidence) -> done
        assert event_types[0] == "retrieval"
        assert event_types[-1] == "done"
        assert event_types[-2] == "final"
        assert events[-2]["data"]["status"] == "not_enough_evidence"

        # Verification must be present and unsupported
        verification_events = [e for e in events if e["type"] == "verification"]
        assert len(verification_events) == 1
        assert verification_events[0]["data"]["status"] == "unsupported"
