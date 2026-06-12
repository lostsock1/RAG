from __future__ import annotations

from app.core.config import Settings
from app.services.contextualizers.base import ChunkContextualizer
from app.services.contextualizers.breadcrumb import BreadcrumbContextualizer
from app.services.contextualizers.llm import LlmChunkContextualizer


def build_chunk_contextualizer(settings: Settings) -> ChunkContextualizer | None:
    """Construct the contextualizer selected by ``contextual_augmentation``.

    Returns None when augmentation is disabled — the pipeline then omits the
    contextualize stage entirely and stays byte-identical to the unaugmented
    path (ADR-0020). The ``llm`` arm fails truthfully at startup when the
    LLM provider settings are missing; there is no silent fallback.
    """
    if settings.contextual_augmentation == "disabled":
        return None
    if settings.contextual_augmentation == "breadcrumb":
        return BreadcrumbContextualizer()
    if settings.contextual_augmentation == "llm":
        if not settings.llm_base_url:
            raise RuntimeError("contextual_augmentation 'llm' requires llm_base_url.")
        if not settings.llm_api_key:
            raise RuntimeError("contextual_augmentation 'llm' requires llm_api_key.")
        return LlmChunkContextualizer(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model_name=settings.llm_model_name,
            max_output_tokens=settings.contextual_llm_max_output_tokens,
        )
    raise RuntimeError(
        f"Unsupported contextual_augmentation: {settings.contextual_augmentation}"
    )
