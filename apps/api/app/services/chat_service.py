from __future__ import annotations

import hashlib
from uuid import UUID

from app.core.request_context import RequestContext
from app.repositories.audit import write_audit_event
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.context import BuildContextRequest, ContextPayload
from app.schemas.generation import GenerateAnswerRequest, GenerateAnswerResponse
from app.schemas.search import SearchRequest, SearchResponse
from app.services.retrieval.base import RetrievalHit

NOT_ENOUGH_EVIDENCE_MESSAGE = "I do not have enough permitted source evidence to answer that yet."


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
    ) -> None:
        self._search_service = search_service
        self._context_builder = context_builder
        self._llm_backend = llm_backend
        self._citation_resolver = citation_resolver
        self._answer_verifier = answer_verifier
        self._max_context_characters = max_context_characters
        self._max_context_blocks = max_context_blocks

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

        citation_ids = [
            citation_id
            for sentence in verification.sentences
            for citation_id in sentence.citation_ids
        ]
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
            tenant_id=UUID(context.tenant_id),
            user_id=UUID(context.user_id),
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
