from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import Settings
from app.services.contextualizers.breadcrumb import BreadcrumbContextualizer
from app.services.contextualizers.factory import build_chunk_contextualizer
from app.services.contextualizers.llm import LlmChunkContextualizer
from app.services.contextualizers.stub import StubChunkContextualizer


def test_factory_disabled_returns_none():
    assert build_chunk_contextualizer(Settings(contextual_augmentation="disabled")) is None


def test_factory_default_is_disabled():
    assert build_chunk_contextualizer(Settings()) is None


def test_factory_breadcrumb():
    contextualizer = build_chunk_contextualizer(
        Settings(contextual_augmentation="breadcrumb")
    )
    assert isinstance(contextualizer, BreadcrumbContextualizer)


def test_factory_llm_uses_llm_provider_settings():
    contextualizer = build_chunk_contextualizer(
        Settings(
            contextual_augmentation="llm",
            llm_base_url="https://ppq.example/v1",
            llm_api_key="secret",
            llm_model_name="fake-model",
            contextual_llm_max_output_tokens=99,
        )
    )
    assert isinstance(contextualizer, LlmChunkContextualizer)
    assert contextualizer._model_name == "fake-model"
    assert contextualizer._max_output_tokens == 99


def test_factory_llm_without_base_url_fails_truthfully():
    with pytest.raises(RuntimeError, match="requires llm_base_url"):
        build_chunk_contextualizer(
            Settings(contextual_augmentation="llm", llm_base_url=None, llm_api_key="secret")
        )


def test_factory_llm_without_api_key_fails_truthfully():
    with pytest.raises(RuntimeError, match="requires llm_api_key"):
        build_chunk_contextualizer(
            Settings(
                contextual_augmentation="llm",
                llm_base_url="https://ppq.example/v1",
                llm_api_key=None,
            )
        )


def test_temporal_runner_builder_injects_contextualizer():
    """build_pipeline_runner_from_settings gives the Temporal path the same
    contextualize stage as the in-process path (ADR-0020)."""
    from app.workflows.temporal_worker import build_pipeline_runner_from_settings

    runner = build_pipeline_runner_from_settings(
        Settings(parser_backend="docling-local", contextual_augmentation="breadcrumb")
    )
    assert runner._stage_names.index("contextualize") == runner._stage_names.index("embed") - 1

    disabled = build_pipeline_runner_from_settings(
        Settings(parser_backend="docling-local", contextual_augmentation="disabled")
    )
    assert "contextualize" not in disabled._stage_names
    assert len(disabled._stage_names) == 7


def test_in_process_dispatcher_passes_contextualizer_through():
    from app.services.parsers.docling_backend import DoclingDocumentParser
    from app.workflows.dispatcher import InProcessDispatcher

    parser = DoclingDocumentParser(converter=lambda req: None)
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        contextualizer=StubChunkContextualizer(),
    )
    assert "contextualize" in dispatcher._runner._stage_names

    plain = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
    )
    assert "contextualize" not in plain._runner._stage_names
