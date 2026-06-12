from __future__ import annotations

from pathlib import Path
import sys
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.schemas.chunks import Chunk
from app.services.contextualizers.base import ContextualizeInput
from app.services.contextualizers.breadcrumb import BreadcrumbContextualizer
from app.services.contextualizers.llm import LlmChunkContextualizer
from app.services.contextualizers.stub import StubChunkContextualizer


def _make_chunk(
    *,
    chunk_id=None,
    text: str = "Leaf chunk text.",
    heading_path: list[str] | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
    context_prefix: str | None = None,
) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id=uuid4(),
        unit_type="paragraph",
        heading_path=heading_path or [],
        page_start=page_start,
        page_end=page_end,
        text=text,
        parent_id=uuid4(),
        chunk_index=0,
        context_prefix=context_prefix,
    )


# ---------------------------------------------------------------------------
# Chunk.search_text (ADR-0020 byte-identity guarantee)
# ---------------------------------------------------------------------------


def test_search_text_with_prefix_prepends_with_newline():
    chunk = _make_chunk(text="Body.", context_prefix="Doc > Section (p. 1)")
    assert chunk.search_text == "Doc > Section (p. 1)\nBody."


def test_search_text_without_prefix_is_text_verbatim():
    chunk = _make_chunk(text="Body.")
    assert chunk.search_text == "Body."


def test_search_text_empty_prefix_is_text_verbatim():
    chunk = _make_chunk(text="Body.", context_prefix="")
    assert chunk.search_text == "Body."


# ---------------------------------------------------------------------------
# BreadcrumbContextualizer
# ---------------------------------------------------------------------------


def _breadcrumb_for(chunk, title="Physics Textbook"):
    result = BreadcrumbContextualizer().contextualize(
        ContextualizeInput(document_title=title, document_text="", leaf_chunks=[chunk])
    )
    return result.get(chunk.id)


def test_breadcrumb_title_headings_and_page():
    chunk = _make_chunk(
        chunk_id=uuid4(),
        heading_path=["Ch3 Thermodynamics", "Entropy"],
        page_start=5,
        page_end=5,
    )
    assert _breadcrumb_for(chunk) == "Physics Textbook > Ch3 Thermodynamics > Entropy (p. 5)"


def test_breadcrumb_page_range():
    chunk = _make_chunk(chunk_id=uuid4(), heading_path=["Intro"], page_start=5, page_end=7)
    assert _breadcrumb_for(chunk) == "Physics Textbook > Intro (pp. 5-7)"


def test_breadcrumb_empty_title_omitted():
    chunk = _make_chunk(chunk_id=uuid4(), heading_path=["Intro"], page_start=1)
    assert _breadcrumb_for(chunk, title="  ") == "Intro (p. 1)"


def test_breadcrumb_blank_headings_filtered():
    chunk = _make_chunk(chunk_id=uuid4(), heading_path=["", "  ", "Real Heading"], page_start=2)
    assert _breadcrumb_for(chunk) == "Physics Textbook > Real Heading (p. 2)"


def test_breadcrumb_page_only():
    chunk = _make_chunk(chunk_id=uuid4(), page_start=9)
    assert _breadcrumb_for(chunk, title="") == "p. 9"


def test_breadcrumb_all_fields_empty_yields_none():
    chunk = _make_chunk(chunk_id=uuid4())
    assert _breadcrumb_for(chunk, title="") is None


def test_breadcrumb_skips_chunks_without_id():
    chunk = _make_chunk(chunk_id=None, heading_path=["Intro"], page_start=1)
    result = BreadcrumbContextualizer().contextualize(
        ContextualizeInput(document_title="T", document_text="", leaf_chunks=[chunk])
    )
    assert result == {}


# ---------------------------------------------------------------------------
# StubChunkContextualizer
# ---------------------------------------------------------------------------


def test_stub_is_deterministic_and_title_tagged():
    chunks = [_make_chunk(chunk_id=uuid4()), _make_chunk(chunk_id=uuid4())]
    payload = ContextualizeInput(
        document_title="Stub Doc", document_text="", leaf_chunks=chunks
    )
    first = StubChunkContextualizer().contextualize(payload)
    second = StubChunkContextualizer().contextualize(payload)
    assert first == second
    assert first == {c.id: "[context: Stub Doc]" for c in chunks}


def test_stub_defaults_title_when_empty():
    chunk = _make_chunk(chunk_id=uuid4())
    result = StubChunkContextualizer().contextualize(
        ContextualizeInput(document_title="", document_text="", leaf_chunks=[chunk])
    )
    assert result[chunk.id] == "[context: doc]"


# ---------------------------------------------------------------------------
# LlmChunkContextualizer (fake transport — no network, no model)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: dict, error: Exception | None = None) -> None:
        self._body = body
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> dict:
        return self._body


class _FakeTransport:
    def __init__(self, body: dict, error: Exception | None = None) -> None:
        self.requests: list[dict] = []
        self._body = body
        self._error = error

    def post(self, url, *, headers, json, timeout):
        self.requests.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return _FakeResponse(self._body, error=self._error)


def _llm_contextualizer(transport, **overrides) -> LlmChunkContextualizer:
    kwargs = dict(
        base_url="https://fake.example/v1/",
        api_key="test-key",
        model_name="fake-model",
        transport=transport,
    )
    kwargs.update(overrides)
    return LlmChunkContextualizer(**kwargs)


def test_llm_contextualizer_prompt_contains_document_and_chunk():
    transport = _FakeTransport({"choices": [{"message": {"content": " Context. "}}]})
    chunk = _make_chunk(chunk_id=uuid4(), text="The second law states X.")
    result = _llm_contextualizer(transport).contextualize(
        ContextualizeInput(
            document_title="T",
            document_text="Full document body about thermodynamics.",
            leaf_chunks=[chunk],
        )
    )

    assert result[chunk.id] == "Context."  # stripped
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request["url"] == "https://fake.example/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    payload = request["json"]
    assert payload["model"] == "fake-model"
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 128
    prompt = payload["messages"][0]["content"]
    assert "Full document body about thermodynamics." in prompt
    assert "The second law states X." in prompt


def test_llm_contextualizer_one_call_per_leaf_chunk():
    transport = _FakeTransport({"choices": [{"message": {"content": "C"}}]})
    chunks = [_make_chunk(chunk_id=uuid4()), _make_chunk(chunk_id=uuid4())]
    result = _llm_contextualizer(transport).contextualize(
        ContextualizeInput(document_title="T", document_text="D", leaf_chunks=chunks)
    )
    assert len(transport.requests) == 2
    assert set(result) == {chunks[0].id, chunks[1].id}


def test_llm_contextualizer_respects_document_char_budget():
    transport = _FakeTransport({"choices": [{"message": {"content": "C"}}]})
    chunk = _make_chunk(chunk_id=uuid4(), text="chunk")
    _llm_contextualizer(transport, document_char_budget=10).contextualize(
        ContextualizeInput(
            document_title="T", document_text="A" * 50, leaf_chunks=[chunk]
        )
    )
    prompt = transport.requests[0]["json"]["messages"][0]["content"]
    assert "A" * 10 in prompt
    assert "A" * 11 not in prompt


def test_llm_contextualizer_empty_content_yields_none():
    transport = _FakeTransport({"choices": [{"message": {"content": "   "}}]})
    chunk = _make_chunk(chunk_id=uuid4())
    result = _llm_contextualizer(transport).contextualize(
        ContextualizeInput(document_title="T", document_text="D", leaf_chunks=[chunk])
    )
    assert result[chunk.id] is None


def test_llm_contextualizer_no_choices_yields_none():
    transport = _FakeTransport({"choices": []})
    chunk = _make_chunk(chunk_id=uuid4())
    result = _llm_contextualizer(transport).contextualize(
        ContextualizeInput(document_title="T", document_text="D", leaf_chunks=[chunk])
    )
    assert result[chunk.id] is None


def test_llm_contextualizer_propagates_transport_errors():
    transport = _FakeTransport({}, error=RuntimeError("upstream 500"))
    chunk = _make_chunk(chunk_id=uuid4())
    with pytest.raises(RuntimeError, match="upstream 500"):
        _llm_contextualizer(transport).contextualize(
            ContextualizeInput(document_title="T", document_text="D", leaf_chunks=[chunk])
        )


def test_llm_contextualizer_skips_chunks_without_id():
    transport = _FakeTransport({"choices": [{"message": {"content": "C"}}]})
    chunk = _make_chunk(chunk_id=None)
    result = _llm_contextualizer(transport).contextualize(
        ContextualizeInput(document_title="T", document_text="D", leaf_chunks=[chunk])
    )
    assert result == {}
    assert transport.requests == []
