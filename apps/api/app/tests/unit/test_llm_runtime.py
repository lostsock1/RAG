from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import Settings
from app.services.llm_runtime import build_llm_backend


def test_llm_runtime_uses_stub_backend_when_disabled() -> None:
    backend = build_llm_backend(settings=Settings(llm_backend="disabled"), state=SimpleNamespace())

    assert backend.__class__.__name__ == "StubLlmBackend"


def test_llm_runtime_passes_generation_defaults_into_stub_backend() -> None:
    backend = build_llm_backend(
        settings=Settings(
            llm_backend="disabled",
            llm_model_name="runtime-model",
            llm_temperature=0.4,
            llm_max_output_tokens=444,
        ),
        state=SimpleNamespace(),
    )

    assert backend._model_name == "runtime-model"
    assert backend._default_temperature == 0.4
    assert backend._default_max_output_tokens == 444


def test_llm_runtime_passes_generation_defaults_into_ppq_backend() -> None:
    backend = build_llm_backend(
        settings=Settings(
            llm_backend="ppq",
            llm_base_url="https://ppq.example/v1",
            llm_api_key="secret",
            llm_model_name="runtime-model",
            llm_temperature=0.4,
            llm_max_output_tokens=444,
        ),
        state=SimpleNamespace(),
    )

    assert backend._model_name == "runtime-model"
    assert backend._default_temperature == 0.4
    assert backend._default_max_output_tokens == 444


def test_llm_runtime_rejects_missing_base_url_for_ppq() -> None:
    with pytest.raises(RuntimeError, match="llm_base_url"):
        build_llm_backend(
            settings=Settings(llm_backend="ppq", llm_base_url=None, llm_api_key="secret"),
            state=SimpleNamespace(),
        )


def test_llm_runtime_rejects_missing_api_key_for_ppq() -> None:
    with pytest.raises(RuntimeError, match="llm_api_key"):
        build_llm_backend(
            settings=Settings(llm_backend="ppq", llm_base_url="https://ppq.example/v1", llm_api_key=None),
            state=SimpleNamespace(),
        )


def test_llm_runtime_rejects_unsupported_backend() -> None:
    settings = Settings.model_construct(
        llm_backend="weird",
        llm_base_url=None,
        llm_api_key=None,
        llm_model_name="meta-llama/Llama-3.3-70B-Instruct",
        llm_temperature=0.0,
        llm_max_output_tokens=512,
    )

    with pytest.raises(RuntimeError, match="Unsupported LLM backend"):
        build_llm_backend(settings=settings, state=SimpleNamespace())


def test_llm_settings_reject_invalid_generation_knobs() -> None:
    with pytest.raises(ValidationError, match="llm_temperature"):
        Settings(llm_temperature=-0.1)

    with pytest.raises(ValidationError, match="llm_max_output_tokens"):
        Settings(llm_max_output_tokens=0)
