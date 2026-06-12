from __future__ import annotations

from app.services.contextualizers.base import ContextualizeInput


class StubChunkContextualizer:
    """Deterministic contextualizer for tests — no model, no network.

    Emits a stable, document-titled prefix so tests can assert that the prefix
    flows through persistence, embedding input, and indexing without loading
    weights or calling an LLM.
    """

    def contextualize(self, payload: ContextualizeInput) -> dict[object, str | None]:
        title = (payload.document_title or "doc").strip()
        return {
            chunk.id: f"[context: {title}]"
            for chunk in payload.leaf_chunks
            if chunk.id is not None
        }
