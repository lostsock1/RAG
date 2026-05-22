from __future__ import annotations

import sys

import pytest
from pathlib import Path
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import Settings
from app.schemas.context import BuildContextRequest
from app.services.context_builder import DefaultContextBuilder
from app.services.retrieval.base import RetrievalHit


def test_context_builder_preserves_order_and_metadata() -> None:
    hits = [
        RetrievalHit(
            document_id="doc-1",
            chunk_id="chunk-1",
            score=0.9,
            text="Alpha evidence",
            page_start=1,
            page_end=2,
            heading_path=["A"],
        ),
        RetrievalHit(
            document_id="doc-2",
            chunk_id="chunk-2",
            score=0.8,
            text="Beta evidence",
            page_start=3,
            page_end=4,
            heading_path=["B"],
        ),
    ]

    payload = DefaultContextBuilder().build(
        BuildContextRequest(
            hits=hits,
            document_titles={"doc-1": "Doc A", "doc-2": "Doc B"},
            max_characters=1000,
            max_blocks=None,
        )
    )

    assert [block.chunk_id for block in payload.blocks] == ["chunk-1", "chunk-2"]
    assert [block.citation_id for block in payload.blocks] == ["chunk-1", "chunk-2"]
    assert [block.document_title for block in payload.blocks] == ["Doc A", "Doc B"]
    assert [block.page_start for block in payload.blocks] == [1, 3]
    assert [block.page_end for block in payload.blocks] == [2, 4]
    assert [block.heading_path for block in payload.blocks] == [["A"], ["B"]]
    assert [block.rank for block in payload.blocks] == [1, 2]
    assert payload.truncated is False


def test_context_builder_truncates_last_block_when_remainder_is_meaningful() -> None:
    hits = [
        RetrievalHit(document_id="doc-1", chunk_id="chunk-1", score=1.0, text="A" * 60),
        RetrievalHit(document_id="doc-2", chunk_id="chunk-2", score=0.9, text="B" * 60),
    ]

    payload = DefaultContextBuilder().build(
        BuildContextRequest(
            hits=hits,
            document_titles={"doc-1": "Doc A", "doc-2": "Doc B"},
            max_characters=80,
            max_blocks=None,
        )
    )

    assert [block.text for block in payload.blocks] == ["A" * 60, "B" * 20]
    assert payload.total_characters == 80
    assert payload.truncated is True


def test_context_builder_omits_too_small_remainder_and_marks_payload_truncated() -> None:
    hits = [
        RetrievalHit(document_id="doc-1", chunk_id="chunk-1", score=1.0, text="A" * 60),
        RetrievalHit(document_id="doc-2", chunk_id="chunk-2", score=0.9, text="B" * 60),
    ]

    payload = DefaultContextBuilder().build(
        BuildContextRequest(
            hits=hits,
            document_titles={"doc-1": "Doc A", "doc-2": "Doc B"},
            max_characters=79,
            max_blocks=None,
        )
    )

    assert [block.text for block in payload.blocks] == ["A" * 60]
    assert payload.block_count == 1
    assert payload.total_characters == 60
    assert payload.truncated is True


def test_context_builder_returns_empty_payload_for_empty_input() -> None:
    payload = DefaultContextBuilder().build(
        BuildContextRequest(
            hits=[],
            document_titles={},
            max_characters=10,
            max_blocks=None,
        )
    )

    assert payload.blocks == []
    assert payload.block_count == 0
    assert payload.total_characters == 0
    assert payload.truncated is False


def test_context_builder_skips_blank_hits() -> None:
    payload = DefaultContextBuilder().build(
        BuildContextRequest(
            hits=[RetrievalHit(document_id="doc-1", chunk_id="chunk-1", score=1.0, text="   ")],
            document_titles={"doc-1": "Doc A"},
            max_characters=10,
            max_blocks=None,
        )
    )

    assert payload.blocks == []
    assert payload.block_count == 0
    assert payload.total_characters == 0
    assert payload.truncated is False


def test_context_builder_respects_max_blocks() -> None:
    hits = [
        RetrievalHit(document_id="doc-1", chunk_id="chunk-1", score=1.0, text="A"),
        RetrievalHit(document_id="doc-2", chunk_id="chunk-2", score=0.9, text="B"),
    ]

    payload = DefaultContextBuilder().build(
        BuildContextRequest(
            hits=hits,
            document_titles={"doc-1": "Doc A", "doc-2": "Doc B"},
            max_characters=10,
            max_blocks=1,
        )
    )

    assert [block.chunk_id for block in payload.blocks] == ["chunk-1"]
    assert payload.block_count == 1
    assert payload.truncated is True


def test_context_builder_rejects_non_positive_budget() -> None:
    with pytest.raises(ValueError, match="max_characters"):
        BuildContextRequest(
            hits=[],
            document_titles={},
            max_characters=0,
            max_blocks=None,
        )


def test_context_builder_runtime_settings_expose_default_budgets() -> None:
    settings = Settings()

    assert settings.context_builder_max_characters == 4000
    assert settings.context_builder_max_blocks is None


def test_context_builder_runtime_settings_allow_disabling_max_blocks() -> None:
    settings = Settings(context_builder_max_blocks=None)

    assert settings.context_builder_max_blocks is None


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("context_builder_max_characters", 0),
        ("context_builder_max_blocks", 0),
    ],
)
def test_context_builder_runtime_settings_reject_non_positive_budgets(
    field_name: str, value: int
) -> None:
    with pytest.raises(ValidationError, match=field_name):
        Settings(**{field_name: value})
