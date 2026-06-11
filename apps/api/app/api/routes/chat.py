from __future__ import annotations

import json
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.answer_verifier import AnswerVerifier
from app.services.answer_verifier_grounding import GroundingAnswerVerifier
from app.services.answer_verifier_nli import NliAnswerVerifier
from app.services.chat_service import ChatService
from app.services.citation_resolver import CitationResolver
from app.services.context_builder import DefaultContextBuilder
from app.services.retrieval.search_service import SearchService

router = APIRouter()


class _PassThroughVerifier:
    """Pass-through verifier that marks every sentence as supported.

    Used when verifier_backend is 'disabled'. This allows the chat
    pipeline to run without any verification overhead.
    """

    def verify(self, *, answer_text: str, context_payload):
        from app.schemas.verification import VerificationSentenceResult, VerificationSummary
        import re

        sentences = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+", answer_text)
            if part.strip()
        ]
        results = [
            VerificationSentenceResult(sentence=s, status="supported", citation_ids=[])
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


@lru_cache(maxsize=4)
def _cached_grounding_verifier(
    model_name: str, threshold: float, unsupported_ratio: float
) -> GroundingAnswerVerifier:
    """Process-cached grounding verifier (ADR-0018 §6 applies identically:
    per-request construction would reload ~3 GB of weights per chat call)."""
    return GroundingAnswerVerifier(
        model_name=model_name,
        threshold=threshold,
        unsupported_ratio=unsupported_ratio,
    )


@lru_cache(maxsize=8)
def _cached_nli_verifier(
    entailment_threshold: float, scoring_mode: str, unsupported_ratio: float
) -> NliAnswerVerifier:
    """Process-cached NLI verifier (ADR-0018 §6).

    Constructing NliAnswerVerifier per request reloads cross-encoder model
    weights on every chat call — several seconds of first-token latency.
    """
    return NliAnswerVerifier(
        entailment_threshold=entailment_threshold,
        scoring_mode=scoring_mode,
        unsupported_ratio=unsupported_ratio,
    )


def _build_chat_service(request: Request) -> ChatService:
    retriever = getattr(request.app.state, "search_retriever", None)
    if retriever is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search retrieval is not configured yet. Configure a search retriever before using /chat.",
        )

    settings = request.app.state.settings
    if settings.llm_backend == "disabled":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM generation is not configured yet. Configure an LLM backend before using /chat.",
        )

    llm_backend = getattr(request.app.state, "llm_backend", None)
    if llm_backend is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM generation is not configured yet. Configure an LLM backend before using /chat.",
        )

    # Select answer verifier backend based on configuration.
    if settings.verifier_backend == "grounding":
        answer_verifier = _cached_grounding_verifier(
            settings.grounding_model_name,
            settings.grounding_threshold,
            settings.grounding_unsupported_ratio,
        )
    elif settings.verifier_backend == "nli":
        answer_verifier = _cached_nli_verifier(
            settings.nli_entailment_threshold,
            settings.nli_scoring_mode,
            settings.nli_unsupported_ratio,
        )
    elif settings.verifier_backend == "disabled":
        answer_verifier = _PassThroughVerifier()
    else:
        answer_verifier = AnswerVerifier()

    return ChatService(
        search_service=SearchService(retriever=retriever),
        context_builder=DefaultContextBuilder(),
        llm_backend=llm_backend,
        citation_resolver=CitationResolver(),
        answer_verifier=answer_verifier,
        max_context_characters=settings.context_builder_max_characters,
        max_context_blocks=settings.context_builder_max_blocks,
        stream_verification_policy=settings.stream_verification_policy,
    )


@router.post("", response_model=ChatResponse)
def chat_route(
    request: Request,
    payload: ChatRequest,
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> ChatResponse:
    return _build_chat_service(request).answer(context=context, payload=payload, delivery_mode="blocking")


@router.post("/stream")
async def chat_stream_route(
    request: Request,
    payload: ChatRequest,
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> StreamingResponse:
    chat_service = _build_chat_service(request)

    async def _events():
        async for event in chat_service.answer_stream(context=context, payload=payload):
            event_type = event["type"]
            event_data = json.dumps(event["data"], separators=(",", ":"), default=str)
            yield f"event: {event_type}\ndata: {event_data}\n\n"

    return StreamingResponse(_events(), media_type="text/event-stream")
