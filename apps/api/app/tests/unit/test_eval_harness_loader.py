"""Tests for tests.eval.harness.loader — YAML dataset loading and filtering."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from tests.eval.harness.loader import (
    EvalDataset,
    EvalQuestion,
    filter_questions,
    load_dataset,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path: Path, content: str) -> Path:
    """Write a YAML string to a file and return the path."""
    p = tmp_path / "dataset.yaml"
    p.write_text(content, encoding="utf-8")
    return p


MINIMAL_YAML = textwrap.dedent("""\
    dataset:
      name: "Test Dataset"
      version: "0.1.0"
      description: "Minimal test dataset"
      thresholds:
        faithfulness: 0.80
    questions:
      - id: "q01"
        type: definition
        category: textbook
        language: en
        query: "What is X?"
        expected:
          status: answered
          answer_contains: ["X"]
          answer_absent: []
          chunk_ids: [null]
      - id: "q02"
        type: negative
        category: textbook
        language: en
        query: "What is Y?"
        expected:
          status: not_found
      - id: "q03"
        type: definition
        category: loose_document
        language: en
        query: "What is Z?"
        expected:
          status: answered
          answer_contains: ["Z"]
""")


# ---------------------------------------------------------------------------
# Loading tests
# ---------------------------------------------------------------------------

class TestLoadDataset:
    def test_loads_minimal_valid_yaml(self, tmp_path: Path):
        path = _write_yaml(tmp_path, MINIMAL_YAML)
        ds = load_dataset(path)

        assert isinstance(ds, EvalDataset)
        assert ds.name == "Test Dataset"
        assert ds.version == "0.1.0"
        assert len(ds.questions) == 3

    def test_parses_question_fields(self, tmp_path: Path):
        path = _write_yaml(tmp_path, MINIMAL_YAML)
        ds = load_dataset(path)

        q = ds.questions[0]
        assert q.id == "q01"
        assert q.type == "definition"
        assert q.category == "textbook"
        assert q.language == "en"
        assert q.query == "What is X?"
        assert q.expected.status == "answered"
        assert q.expected.answer_contains == ["X"]
        assert q.expected.answer_absent == []
        assert q.expected.chunk_ids == [None]

    def test_defaults_for_missing_optional_fields(self, tmp_path: Path):
        path = _write_yaml(tmp_path, MINIMAL_YAML)
        ds = load_dataset(path)

        # q02 has no retrieval or acl section
        q02 = ds.questions[1]
        assert q02.retrieval.expected_recall_k is None
        assert q02.acl.user_context == "default"

    def test_thresholds_parsed(self, tmp_path: Path):
        path = _write_yaml(tmp_path, MINIMAL_YAML)
        ds = load_dataset(path)

        assert ds.thresholds.faithfulness == 0.80
        # defaults for unspecified thresholds
        assert ds.thresholds.citation_accuracy == 0.90
        assert ds.thresholds.negative_compliance == 0.90

    def test_rejects_missing_id(self, tmp_path: Path):
        bad_yaml = textwrap.dedent("""\
            dataset:
              name: "Bad"
              version: "0.1.0"
              description: "Missing id"
              thresholds: {}
            questions:
              - type: definition
                category: textbook
                language: en
                query: "What?"
                expected:
                  status: answered
        """)
        path = _write_yaml(tmp_path, bad_yaml)
        with pytest.raises(ValueError, match="id"):
            load_dataset(path)

    def test_rejects_missing_type(self, tmp_path: Path):
        bad_yaml = textwrap.dedent("""\
            dataset:
              name: "Bad"
              version: "0.1.0"
              description: "Missing type"
              thresholds: {}
            questions:
              - id: "q01"
                category: textbook
                language: en
                query: "What?"
                expected:
                  status: answered
        """)
        path = _write_yaml(tmp_path, bad_yaml)
        with pytest.raises(ValueError, match="type"):
            load_dataset(path)

    def test_rejects_missing_query(self, tmp_path: Path):
        bad_yaml = textwrap.dedent("""\
            dataset:
              name: "Bad"
              version: "0.1.0"
              description: "Missing query"
              thresholds: {}
            questions:
              - id: "q01"
                type: definition
                category: textbook
                language: en
                expected:
                  status: answered
        """)
        path = _write_yaml(tmp_path, bad_yaml)
        with pytest.raises(ValueError, match="query"):
            load_dataset(path)

    def test_rejects_missing_expected(self, tmp_path: Path):
        bad_yaml = textwrap.dedent("""\
            dataset:
              name: "Bad"
              version: "0.1.0"
              description: "Missing expected"
              thresholds: {}
            questions:
              - id: "q01"
                type: definition
                category: textbook
                language: en
                query: "What?"
        """)
        path = _write_yaml(tmp_path, bad_yaml)
        with pytest.raises(ValueError, match="expected"):
            load_dataset(path)

    def test_rejects_missing_expected_status(self, tmp_path: Path):
        bad_yaml = textwrap.dedent("""\
            dataset:
              name: "Bad"
              version: "0.1.0"
              description: "Missing status"
              thresholds: {}
            questions:
              - id: "q01"
                type: definition
                category: textbook
                language: en
                query: "What?"
                expected:
                  answer_contains: ["X"]
        """)
        path = _write_yaml(tmp_path, bad_yaml)
        with pytest.raises(ValueError, match="status"):
            load_dataset(path)

    def test_rejects_invalid_status_value(self, tmp_path: Path):
        bad_yaml = textwrap.dedent("""\
            dataset:
              name: "Bad"
              version: "0.1.0"
              description: "Invalid status"
              thresholds: {}
            questions:
              - id: "q01"
                type: definition
                category: textbook
                language: en
                query: "What?"
                expected:
                  status: maybe
        """)
        path = _write_yaml(tmp_path, bad_yaml)
        with pytest.raises(ValueError, match="status"):
            load_dataset(path)

    def test_unknown_type_does_not_raise(self, tmp_path: Path):
        """Forward compatibility: unknown question types are accepted."""
        yaml_str = textwrap.dedent("""\
            dataset:
              name: "Future"
              version: "0.1.0"
              description: "Future type"
              thresholds: {}
            questions:
              - id: "q01"
                type: future_type_xyz
                category: textbook
                language: en
                query: "What?"
                expected:
                  status: answered
        """)
        path = _write_yaml(tmp_path, yaml_str)
        ds = load_dataset(path)
        assert ds.questions[0].type == "future_type_xyz"

    def test_load_real_heldout_v1_smoke(self):
        """Smoke test: the real dataset loads without error."""
        real_path = Path("docs/uber-rag/eval/heldout-v1.yaml")
        if not real_path.exists():
            pytest.skip("heldout-v1.yaml not found")
        ds = load_dataset(real_path)
        assert ds.name == "Heldout v1"
        assert len(ds.questions) > 0


# ---------------------------------------------------------------------------
# Filter tests
# ---------------------------------------------------------------------------

class TestFilterQuestions:
    @pytest.fixture()
    def questions(self, tmp_path: Path) -> list[EvalQuestion]:
        path = _write_yaml(tmp_path, MINIMAL_YAML)
        ds = load_dataset(path)
        return ds.questions

    def test_filter_by_type(self, questions: list[EvalQuestion]):
        result = filter_questions(questions, type="definition")
        assert all(q.type == "definition" for q in result)
        assert len(result) == 2

    def test_filter_by_category(self, questions: list[EvalQuestion]):
        result = filter_questions(questions, category="textbook")
        assert all(q.category == "textbook" for q in result)
        assert len(result) == 2

    def test_filter_by_type_and_category(self, questions: list[EvalQuestion]):
        result = filter_questions(questions, type="definition", category="textbook")
        assert len(result) == 1
        assert result[0].id == "q01"

    def test_filter_with_limit(self, questions: list[EvalQuestion]):
        result = filter_questions(questions, limit=2)
        assert len(result) == 2

    def test_filter_no_filters_returns_all(self, questions: list[EvalQuestion]):
        result = filter_questions(questions)
        assert len(result) == len(questions)

    def test_filter_limit_zero_returns_empty(self, questions: list[EvalQuestion]):
        result = filter_questions(questions, limit=0)
        assert result == []
