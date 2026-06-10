from __future__ import annotations

import functools
import hashlib
import threading
from typing import AsyncIterator, cast
from uuid import UUID

import anyio

from app.core.request_context import RequestContext
from app.repositories.audit import write_audit_event
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.context import BuildContextRequest, ContextPayload
from app.schemas.generation import GenerateAnswerRequest, GenerateAnswerResponse
from app.schemas.search import SearchRequest, SearchResponse
from app.services.retrieval.base import RetrievalHit
from app.services.streaming_verifier import SentenceAssembler

NOT_ENOUGH_EVIDENCE_MESSAGE = "I do not have enough permitted source evidence to answer that yet."

# Process-wide verification gate (ADR-0018 §3 measurement follow-up): one NLI
# predict at a time, each using torch's full intra-op thread count. Concurrent
# per-sentence predicts from parallel streams oversubscribe the CPU and thrash —
# measured 2026-06-10: P50 first-token 8.0s / totals ~13.5s at 5 concurrent
# without the gate vs the same verifier being fast solo (request 0: 2.6s).
# Taken inside the worker thread, so it is event-loop-agnostic (asyncio/trio).
_VERIFICATION_GATE = threading.Semaphore(1)


class ChatService:
    def __init__(
        self,
        *,
        search_service,
        context_builder,
        llm_backend,
        citation_resolver,
        answer_verifier,
        max_context_characters: int,
        max_context_blocks: int | None,
        stream_verification_policy: str = "retract",
    ) -> None:
        self._search_service = search_service
        self._context_builder = context_builder
        self._llm_backend = llm_backend
        self._citation_resolver = citation_resolver
        self._answer_verifier = answer_verifier
        self._max_context_characters = max_context_characters
        self._max_context_blocks = max_context_blocks
        self._stream_verification_policy = stream_verification_policy

    def answer(
        self,
        *,
        context: RequestContext,
        payload: ChatRequest,
        delivery_mode: str = "blocking",
    ) -> ChatResponse:
        search_response = self._search_service.search(
            context=context,
            payload=SearchRequest(query=payload.question, top_k=payload.top_k),
        )
        context_payload = self._context_builder.build(
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
                max_characters=self._max_context_characters,
                max_blocks=self._max_context_blocks,
            )
        )

        if search_response.total == 0 or context_payload.block_count == 0:
            result = ChatResponse(
                answer_text=NOT_ENOUGH_EVIDENCE_MESSAGE,
                status="not_enough_evidence",
                model_name=None,
                provider_name=None,
                context_block_count=context_payload.block_count,
                retrieval_hit_count=search_response.total,
                usage=None,
            )
            self._write_chat_audit_event(
                context=context,
                payload=payload,
                search_response=search_response,
                context_payload=context_payload,
                result=result,
                generation_response=None,
                delivery_mode=delivery_mode,
            )
            return result

        generation_response = self._llm_backend.generate(
            GenerateAnswerRequest(question=payload.question, context_payload=context_payload)
        )

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
            )
            return result

        citation_ids = list(
            dict.fromkeys(
                citation_id
                for sentence in verification.sentences
                for citation_id in sentence.citation_ids
            )
        )
        citations = self._citation_resolver.resolve(
            citation_ids=citation_ids, hits=search_response.items
        ).items

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
        self._write_chat_audit_event(
            context=context,
            payload=payload,
            search_response=search_response,
            context_payload=context_payload,
            result=result,
            generation_response=generation_response,
            delivery_mode=delivery_mode,
        )
        return result

    async def answer_stream(
        self,
        *,
        context: RequestContext,
        payload: ChatRequest,
    ) -> AsyncIterator[dict]:
        """Stream answer generation with sentence-incremental verification (ADR-0018).

        Tokens are assembled into sentences as they arrive; each completed
        sentence is verified against the retrieved context before its text is
        emitted. No unverified text ever reaches the client — the evidence
        discipline invariant holds at sentence granularity, and first-token
        latency is first-sentence latency instead of full-answer latency.

        On an unsupported sentence the configured policy applies:
        - "retract" (default): stop, emit a retraction (only if tokens were
          already emitted), finalize as not_enough_evidence.
        - "truncate": keep the verified prefix, finalize as answered with
          truncated=true.

        Yields event dicts with 'type' and 'data' keys:
        - {"type": "retrieval", "data": {"hit_count": N, "block_count": M}}
        - {"type": "token", "data": {"text": "<one verified sentence>"}}
        - {"type": "verification", "data": {"status": "supported"|"unsupported"}}  (aggregate, after tokens)
        - {"type": "retraction", "data": {"reason": "verification_failed"}}  (retract policy, mid-stream failure only)
        - {"type": "citations", "data": {"citations": [...]}}
        - {"type": "final", "data": {"status": "answered"|"not_enough_evidence", "answer_text": "...", ["truncated": true]}}
        - {"type": "done", "data": {}}
        """
        # 1. Search (blocking — fast)
        search_response = self._search_service.search(
            context=context,
            payload=SearchRequest(query=payload.question, top_k=payload.top_k),
        )
        context_payload = self._context_builder.build(
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
                max_characters=self._max_context_characters,
                max_blocks=self._max_context_blocks,
            )
        )

        yield {"type": "retrieval", "data": {
            "hit_count": search_response.total,
            "block_count": context_payload.block_count,
        }}

        # 2. Check if we have evidence
        if search_response.total == 0 or context_payload.block_count == 0:
            yield {"type": "final", "data": {
                "status": "not_enough_evidence",
                "answer_text": NOT_ENOUGH_EVIDENCE_MESSAGE,
            }}
            yield {"type": "done", "data": {}}
            return

        # 3. Stream LLM tokens through the sentence assembler; verify each
        # completed sentence before emitting it (ADR-0018). Verification runs
        # in a worker thread so NLI inference never stalls the event loop.
        assembler = SentenceAssembler()
        emitted: list[str] = []
        citation_ids: list[str] = []
        failed = False

        def _verify_gated(stripped_sentence: str):
            with _VERIFICATION_GATE:
                return self._answer_verifier.verify(
                    answer_text=stripped_sentence,
                    context_payload=context_payload,
                )

        async def _sentence_is_supported(sentence_text: str) -> bool:
            stripped = sentence_text.strip()
            if not stripped:
                return True
            summary = await anyio.to_thread.run_sync(
                functools.partial(_verify_gated, stripped)
            )
            if summary.status != "supported":
                return False
            for sentence_result in summary.sentences:
                citation_ids.extend(sentence_result.citation_ids)
            return True

        async for event in self._llm_backend.generate_stream(
            GenerateAnswerRequest(question=payload.question, context_payload=context_payload)
        ):
            if event.is_final:
                break
            for sentence in assembler.feed(event.text):
                if await _sentence_is_supported(sentence):
                    emitted.append(sentence)
                    yield {"type": "token", "data": {"text": sentence}}
                else:
                    failed = True
                    break
            if failed:
                break

        if not failed:
            tail = assembler.flush()
            if tail is not None:
                if await _sentence_is_supported(tail):
                    emitted.append(tail)
                    yield {"type": "token", "data": {"text": tail}}
                else:
                    failed = True

        answer_text = "".join(emitted)

        # 4. Failure path — apply the configured policy
        if failed:
            yield {"type": "verification", "data": {"status": "unsupported"}}
            if self._stream_verification_policy == "truncate" and emitted:
                unique_citation_ids = list(dict.fromkeys(citation_ids))
                citations = self._citation_resolver.resolve(
                    citation_ids=unique_citation_ids, hits=search_response.items
                ).items
                yield {"type": "citations", "data": {"citations": [c.model_dump() for c in citations]}}
                yield {"type": "final", "data": {
                    "status": "answered",
                    "answer_text": answer_text,
                    "truncated": True,
                }}
                yield {"type": "done", "data": {}}
                return
            if emitted:
                yield {"type": "retraction", "data": {"reason": "verification_failed"}}
            yield {"type": "final", "data": {
                "status": "not_enough_evidence",
                "answer_text": NOT_ENOUGH_EVIDENCE_MESSAGE,
            }}
            yield {"type": "done", "data": {}}
            return

        # 5. Empty generation — nothing was ever verifiable
        if not emitted:
            yield {"type": "verification", "data": {"status": "unsupported"}}
            yield {"type": "final", "data": {
                "status": "not_enough_evidence",
                "answer_text": NOT_ENOUGH_EVIDENCE_MESSAGE,
            }}
            yield {"type": "done", "data": {}}
            return

        # 6. Aggregate verification + citations + final
        yield {"type": "verification", "data": {"status": "supported"}}

        unique_citation_ids = list(dict.fromkeys(citation_ids))
        citations = self._citation_resolver.resolve(
            citation_ids=unique_citation_ids, hits=search_response.items
        ).items

        yield {"type": "citations", "data": {"citations": [c.model_dump() for c in citations]}}
        yield {"type": "final", "data": {
            "status": "answered",
            "answer_text": answer_text,
        }}
        yield {"type": "done", "data": {}}

    def _write_chat_audit_event(
        self,
        *,
        context: RequestContext,
        payload: ChatRequest,
        search_response: SearchResponse,
        context_payload: ContextPayload,
        result: ChatResponse,
        generation_response: GenerateAnswerResponse | None,
        delivery_mode: str,
    ) -> None:
        write_audit_event(
            tenant_id=cast(str, UUID(context.tenant_id)),
            user_id=cast(str, UUID(context.user_id)),
            action="chat.answer",
            resource_type="document",
            resource_id=None,
            details={
                "query_sha256": hashlib.sha256(payload.question.encode("utf-8")).hexdigest(),
                "query_length": len(payload.question),
                "top_k": payload.top_k,
                "delivery_mode": delivery_mode,
                "filters_applied": ["acl"],
                "retrieved_document_ids": [item.document_id for item in search_response.items],
                "retrieval_hit_count": search_response.total,
                "context_block_count": context_payload.block_count,
                "citations_returned": len(result.citations),
                "llm_invoked": generation_response is not None,
                "model_name": generation_response.model_name if generation_response is not None else None,
                "provider_name": generation_response.provider_name if generation_response is not None else None,
                "verification_status": result.verification.status if result.verification else "not_run",
                "outcome_status": result.status,
            },
        )
