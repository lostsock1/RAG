"""Write eval reports as JSON and Markdown."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tests.eval.harness.scorer import AggregateReport


def write_json_report(report: AggregateReport, output_path: str | Path) -> None:
    """Write report as JSON."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_questions": report.total_questions,
        "faithfulness": report.faithfulness,
        "negative_answer_compliance": report.negative_answer_compliance,
        "acl_leakage_count": report.acl_leakage_count,
        "answer_contains_pass_rate": report.answer_contains_pass_rate,
        "answer_absent_pass_rate": report.answer_absent_pass_rate,
        "per_question": report.per_question,
    }

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_markdown_report(report: AggregateReport, output_path: str | Path) -> None:
    """Write report as human-readable Markdown."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_report(report), encoding="utf-8")


def format_report(report: AggregateReport) -> str:
    """Return Markdown string for the report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = []
    lines.append("# Eval Report")
    lines.append("")
    lines.append(f"**Generated:** {now}")
    lines.append(f"**Total questions:** {report.total_questions}")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Faithfulness | {report.faithfulness:.2%} |")
    lines.append(f"| Negative answer compliance | {report.negative_answer_compliance:.2%} |")
    lines.append(f"| ACL leakage count | {report.acl_leakage_count} |")
    lines.append(f"| Answer contains pass rate | {report.answer_contains_pass_rate:.2%} |")
    lines.append(f"| Answer absent pass rate | {report.answer_absent_pass_rate:.2%} |")
    lines.append("")

    # Per-question details
    if report.per_question:
        lines.append("## Per-Question Details")
        lines.append("")
        lines.append("| Question ID | Type | Details |")
        lines.append("|-------------|------|---------|")
        for q in report.per_question:
            qid = q.get("question_id", "?")
            qtype = q.get("type", "?")
            if qtype == "answered":
                details = (
                    f"status_match={q.get('status_match')}, "
                    f"contains={q.get('answer_contains_pass_rate', 0):.0%}, "
                    f"absent_fail={q.get('answer_absent_fail')}, "
                    f"faith={q.get('faithfulness', 0):.2f}"
                )
            elif qtype == "negative":
                details = f"compliant={q.get('compliant')}"
            elif qtype == "acl":
                details = f"leak={q.get('leak')}"
            else:
                details = ""
            lines.append(f"| {qid} | {qtype} | {details} |")
        lines.append("")

    return "\n".join(lines)
