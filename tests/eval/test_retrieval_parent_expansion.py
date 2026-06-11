"""E1 eval gate: parent-child expansion ON vs the committed baseline (OFF).

Audit result (2026-06-11): expansion existed and was production-wired, but it
ran BEFORE rerank, replaced the leaf chunk_id with a whole-document parent
(loose profile: parent = entire doc, up to 8192 chars), was uncapped,
ungated, and stubbed off in the eval fixture — so the committed baseline
measured a pipeline production never ran. E1 conformed the implementation to
the master-plan spec (rerank leaves first, swap in a capped leaf-centered
parent window, keep the leaf chunk_id for citations, dedupe shared parents,
config gate) and this test runs the C3 rig over the ON arm.

Metric semantics note: leaf ids are preserved by design, so deltas vs the
baseline come only from dedupe compaction (directly-retrieved parents
collapsing into their expanded leaves, freeing top-k slots). The answer-path
benefit (parent context for the LLM + verifier) is invisible to id-based
retrieval metrics — recorded in the report, not claimed as a metric win.

The positive control asserts the parent lookup actually resolved rows: an
id-format mismatch would otherwise make this arm silently identical to OFF.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.eval.conftest import EvalStack
from tests.eval.harness.cli import compare_reports
from tests.eval.harness.ground_truth import resolve_expected_chunk_groups
from tests.eval.harness.loader import load_dataset
from tests.eval.harness.scorer import grouped_mrr_at_k, grouped_ndcg_at_k, grouped_recall_at_k

EVAL_DIR = Path(__file__).parent
HELDOUT_PATH = EVAL_DIR.parent.parent / "docs" / "uber-rag" / "eval" / "heldout-v1.yaml"
BASELINE_REPORT_PATH = EVAL_DIR / "reports" / "retrieval_baseline.json"
REPORT_PATH = EVAL_DIR / "reports" / "retrieval_parent_expansion.json"

K_VALUES = (5, 10, 20)
TOP_K = 20


@pytest.mark.slow
def test_retrieval_parent_expansion_arm(eval_stack: EvalStack):
    from app.schemas.search import SearchRequest

    dataset = load_dataset(HELDOUT_PATH)
    questions = [q for q in dataset.questions if q.evidence]
    assert len(questions) >= 60

    per_question: list[dict] = []
    expanded_block_questions = 0
    for question in questions:
        groups = resolve_expected_chunk_groups(
            evidence=question.evidence,
            document_ids_by_slug=eval_stack.document_ids_by_slug,
        )
        assert groups, f"{question.id}: empty evidence groups"

        response = eval_stack.search_service_parent_expansion.search(
            context=eval_stack.context,
            payload=SearchRequest(query=question.query, top_k=TOP_K),
        )
        ranked_ids = [item.chunk_id for item in response.items if item.chunk_id]

        metrics = {}
        for k in K_VALUES:
            metrics[f"recall@{k}"] = round(grouped_recall_at_k(ranked_ids, groups, k), 4)
            metrics[f"ndcg@{k}"] = round(grouped_ndcg_at_k(ranked_ids, groups, k), 4)
        metrics["mrr@10"] = round(grouped_mrr_at_k(ranked_ids, groups, 10), 4)

        per_question.append({
            "question_id": question.id,
            "type": question.type,
            "language": question.language,
            "evidence_group_count": len(groups),
            "retrieved_count": len(ranked_ids),
            "metrics": metrics,
            "top_5_chunk_ids": ranked_ids[:5],
        })

    def _mean_over(rows: list[dict], metric: str) -> float:
        return round(sum(r["metrics"][metric] for r in rows) / len(rows), 4) if rows else 0.0

    metric_keys = [f"recall@{k}" for k in K_VALUES] + [f"ndcg@{k}" for k in K_VALUES] + ["mrr@10"]
    aggregates = {m: _mean_over(per_question, m) for m in metric_keys}

    by_language: dict[str, dict] = {}
    for lang in sorted({q["language"] for q in per_question}):
        rows = [q for q in per_question if q["language"] == lang]
        by_language[lang] = {
            "question_count": len(rows),
            **{m: _mean_over(rows, m) for m in metric_keys},
        }

    repo = eval_stack.parent_expansion_repo
    report = {
        "report": "retrieval_parent_expansion",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question_count": len(per_question),
        "retriever": {
            "dense": "BGE-M3 (real) via in-memory Qdrant",
            "lexical": "disabled (stub) — dense-only eval fixture",
            "reranker": "stub (pass-through)",
            "parent_expansion": (
                "ENABLED (E1): after-rerank, leaf chunk_id preserved, parent text "
                "capped at 2048 chars centered on the leaf, shared parents deduped"
            ),
            "top_k": TOP_K,
        },
        "ground_truth": "span-anchored (heldout-v1 evidence blocks, resolved at runtime)",
        "positive_control": {
            "parent_lookups": repo.lookups,
            "parent_rows_resolved": repo.resolved,
        },
        "aggregates": aggregates,
        "by_language": by_language,
        "per_question": per_question,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nParent-expansion arm written: {REPORT_PATH} ({len(per_question)} questions)")
    print("aggregate:", json.dumps(aggregates))
    print(f"positive control: {repo.lookups} lookups, {repo.resolved} parent rows resolved")

    # Positive control: the production lookup must actually resolve parents
    # against the eval SQLite stack (guards the id-format silent no-op).
    assert repo.lookups >= len(questions)
    assert repo.resolved > 0, (
        "Parent lookup resolved zero rows — expansion arm is silently identical "
        "to the baseline (id-format mismatch?)"
    )

    # Eval gate: no watched aggregate may regress beyond the C4 tolerances.
    regressions = compare_reports(BASELINE_REPORT_PATH, REPORT_PATH)
    assert not regressions, f"Parent expansion regressed the baseline: {regressions}"
