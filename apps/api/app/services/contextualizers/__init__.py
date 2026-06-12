"""Chunk contextualizers (ADR-0020 contextual chunk augmentation).

A contextualizer produces a short situating prefix for each leaf chunk, used
to enrich the chunk's *searchable* representation (embedding + BM25) without
changing its display/citation text. Two production arms:

- ``BreadcrumbContextualizer`` — no LLM; title + heading path + page anchor.
- ``LlmChunkContextualizer`` — 50-100-token LLM-generated situating context
  per the Anthropic Contextual Retrieval recipe.
"""
from __future__ import annotations

from app.services.contextualizers.base import (
    ChunkContextualizer,
    ContextualizeInput,
)
from app.services.contextualizers.breadcrumb import BreadcrumbContextualizer
from app.services.contextualizers.llm import LlmChunkContextualizer
from app.services.contextualizers.stub import StubChunkContextualizer

__all__ = [
    "ChunkContextualizer",
    "ContextualizeInput",
    "BreadcrumbContextualizer",
    "LlmChunkContextualizer",
    "StubChunkContextualizer",
]
