from __future__ import annotations

from app.core.config import Settings
from app.services.llm_backend import LlmBackend, PpqLlmBackend, StubLlmBackend


def build_llm_backend(*, settings: Settings, state: object) -> LlmBackend:
    backend = getattr(state, "llm_backend", None)
    if backend is not None:
        return backend
    if settings.llm_backend in {"disabled", "stub"}:
        return StubLlmBackend(
            model_name=settings.llm_model_name,
            default_temperature=settings.llm_temperature,
            default_max_output_tokens=settings.llm_max_output_tokens,
        )
    if settings.llm_backend == "ppq":
        if not settings.llm_base_url:
            raise RuntimeError("LLM backend 'ppq' requires llm_base_url.")
        if not settings.llm_api_key:
            raise RuntimeError("LLM backend 'ppq' requires llm_api_key.")
        return PpqLlmBackend(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model_name=settings.llm_model_name,
            default_temperature=settings.llm_temperature,
            default_max_output_tokens=settings.llm_max_output_tokens,
        )
    raise RuntimeError(f"Unsupported LLM backend: {settings.llm_backend}")
