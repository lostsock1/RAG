from __future__ import annotations

from typing import Protocol

from app.schemas.context import BuildContextRequest, ContextBlock, ContextPayload


MIN_MEANINGFUL_REMAINDER_CHARACTERS = 20


class ContextBuilder(Protocol):
    def build(self, request: BuildContextRequest) -> ContextPayload: ...


class DefaultContextBuilder:
    def build(self, request: BuildContextRequest) -> ContextPayload:
        remaining = request.max_characters
        blocks = []
        truncated = False
        next_rank = 1

        for hit in request.hits:
            if request.max_blocks is not None and len(blocks) >= request.max_blocks:
                truncated = True
                break
            if not hit.text.strip():
                continue
            if remaining <= 0:
                truncated = True
                break

            text = hit.text
            if len(text) > remaining:
                # Keep the truncation rule deterministic: only emit a final partial
                # block when the leftover budget is large enough to carry some
                # meaningful evidence instead of a tiny tail fragment.
                if remaining < MIN_MEANINGFUL_REMAINDER_CHARACTERS:
                    truncated = True
                    break
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
