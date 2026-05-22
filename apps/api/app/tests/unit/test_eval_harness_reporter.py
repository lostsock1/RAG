"""Tests for tests.eval.harness.reporter — JSON and Markdown report generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.eval.harness.scorer import AggregateReport
from tests.eval.harness.reporter import format_report, write_json_report, write_markdown_report


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_report() -> AggregateReport:
    return AggregateReport(
        total_questions=4,
        faithfulness=0.85,
        negative_answer_compliance=0.5,
        acl_leakage_count=1,
        answer_contains_pass_rate=0.75,
        answer_absent_pass_rate=1.0,
        per_question=[
            {
                "question_id": "q01",
                "type": "answered",
                "status_match": True,
                "faithfulness": 0.9,
            },
            {
                "question_id": "q02",
                "type": "answered",
                "status_match": True,
                "faithfulness": 0.8,
            },
            {
                "question_id": "q03",
                "type": "negative",
                "compliant": True,
            },
            {
                "question_id": "q04",
                "type": "acl",
                "leak": True,
                "leak_detail": "forbidden content",
            },
        ],
    )


# ---------------------------------------------------------------------------
# write_json_report
# ---------------------------------------------------------------------------

class TestWriteJsonReport:
    def test_produces_valid_json(self, tmp_path: Path, sample_report: AggregateReport):
        out = tmp_path / "report.json"
        write_json_report(sample_report, out)

        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["total_questions"] == 4
        assert data["faithfulness"] == 0.85
        assert len(data["per_question"]) == 4

    def test_accepts_string_path(self, tmp_path: Path, sample_report: AggregateReport):
        out = str(tmp_path / "report.json")
        write_json_report(sample_report, out)
        assert Path(out).exists()


# ---------------------------------------------------------------------------
# write_markdown_report
# ---------------------------------------------------------------------------

class TestWriteMarkdownReport:
    def test_produces_valid_markdown(self, tmp_path: Path, sample_report: AggregateReport):
        out = tmp_path / "report.md"
        write_markdown_report(sample_report, out)

        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "# " in content  # has a heading
        assert "faithfulness" in content.lower()

    def test_accepts_string_path(self, tmp_path: Path, sample_report: AggregateReport):
        out = str(tmp_path / "report.md")
        write_markdown_report(sample_report, out)
        assert Path(out).exists()


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_includes_key_metrics(self, sample_report: AggregateReport):
        md = format_report(sample_report)

        assert "85.00%" in md  # faithfulness
        assert "50.00%" in md  # negative compliance
        assert "1" in md  # acl_leakage_count
        assert "75.00%" in md  # answer_contains_pass_rate

    def test_includes_per_question_table(self, sample_report: AggregateReport):
        md = format_report(sample_report)

        assert "q01" in md
        assert "q04" in md

    def test_empty_report(self):
        report = AggregateReport(
            total_questions=0,
            faithfulness=0.0,
            negative_answer_compliance=0.0,
            acl_leakage_count=0,
            answer_contains_pass_rate=0.0,
            answer_absent_pass_rate=0.0,
        )
        md = format_report(report)

        assert "0" in md
        assert "total" in md.lower() or "questions" in md.lower()
