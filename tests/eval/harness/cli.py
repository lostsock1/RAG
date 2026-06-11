"""CLI entry point for the eval harness.

Usage::

    python -m tests.eval.harness.cli --dataset path/to/heldout-v1.yaml --output path/to/report.json [--filter type=negative] [--limit 15]
    python -m tests.eval.harness.cli --compare-baseline baseline.json --candidate fresh.json [--advisory]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tests.eval.harness.loader import filter_questions, load_dataset
from tests.eval.harness.reporter import write_json_report
from tests.eval.harness.scorer import AggregateReport

# Regression ceilings for the CI gate (master plan C4): a candidate run fails
# when any watched aggregate drops below baseline by more than its tolerance.
REGRESSION_TOLERANCES = {
    "recall@10": 0.02,
    "ndcg@10": 0.02,
    "mrr@10": 0.02,
}


def compare_reports(baseline_path: str | Path, candidate_path: str | Path) -> list[str]:
    """Compare two retrieval reports; return a list of regression messages."""
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    candidate = json.loads(Path(candidate_path).read_text(encoding="utf-8"))

    baseline_agg = baseline.get("aggregates", {})
    candidate_agg = candidate.get("aggregates", {})

    regressions: list[str] = []
    print(f"{'metric':<12} {'baseline':>10} {'candidate':>10} {'delta':>9}")
    for metric, tolerance in REGRESSION_TOLERANCES.items():
        if metric not in baseline_agg or metric not in candidate_agg:
            regressions.append(f"{metric}: missing from one of the reports")
            continue
        base_v = float(baseline_agg[metric])
        cand_v = float(candidate_agg[metric])
        delta = cand_v - base_v
        marker = ""
        if delta < -tolerance:
            marker = "  << REGRESSION"
            regressions.append(
                f"{metric}: {base_v:.4f} -> {cand_v:.4f} (drop {-delta:.4f} > tolerance {tolerance})"
            )
        print(f"{metric:<12} {base_v:>10.4f} {cand_v:>10.4f} {delta:>+9.4f}{marker}")
    return regressions


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Uber-RAG eval harness")
    parser.add_argument(
        "--dataset",
        help="Path to the eval dataset YAML file",
    )
    parser.add_argument(
        "--output",
        help="Path for the output JSON report",
    )
    parser.add_argument(
        "--compare-baseline",
        help="Baseline report JSON to compare against (enables compare mode)",
    )
    parser.add_argument(
        "--candidate",
        help="Candidate report JSON for compare mode",
    )
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="Compare mode: report regressions but exit 0",
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

    # Compare mode (CI advisory gate, master plan C4)
    if args.compare_baseline:
        if not args.candidate:
            parser.error("--compare-baseline requires --candidate")
        regressions = compare_reports(args.compare_baseline, args.candidate)
        if regressions:
            print("\nRegressions detected:")
            for r in regressions:
                print(f"  - {r}")
            if args.advisory:
                print("Advisory mode: exiting 0 despite regressions.")
                return
            sys.exit(1)
        print("\nNo regressions.")
        return

    if not args.dataset or not args.output:
        parser.error("--dataset and --output are required outside compare mode")

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
