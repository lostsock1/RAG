"""CLI entry point for the eval harness.

Usage::

    python -m tests.eval.harness.cli --dataset path/to/heldout-v1.yaml --output path/to/report.json [--filter type=negative] [--limit 15]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tests.eval.harness.loader import filter_questions, load_dataset
from tests.eval.harness.reporter import write_json_report
from tests.eval.harness.scorer import AggregateReport


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Uber-RAG eval harness")
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to the eval dataset YAML file",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path for the output JSON report",
    )
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        help="Filter in KEY=VALUE format (e.g., type=negative, category=textbook)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of questions to include",
    )

    args = parser.parse_args(argv)

    # Load dataset
    dataset = load_dataset(args.dataset)

    # Apply filters
    questions = dataset.questions
    filter_kwargs: dict = {}
    for f in args.filter:
        key, _, value = f.partition("=")
        if key in ("type", "category"):
            filter_kwargs[key] = value
    if args.limit is not None:
        filter_kwargs["limit"] = args.limit

    questions = filter_questions(questions, **filter_kwargs)

    # For this skeleton step, produce an empty report (no runner execution)
    report = AggregateReport(
        total_questions=len(questions),
        faithfulness=0.0,
        negative_answer_compliance=0.0,
        acl_leakage_count=0,
        answer_contains_pass_rate=0.0,
        answer_absent_pass_rate=0.0,
    )

    write_json_report(report, args.output)
    print(f"Report written to {args.output} ({report.total_questions} questions)")


if __name__ == "__main__":
    main()
