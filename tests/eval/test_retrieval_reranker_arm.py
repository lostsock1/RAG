"""Real-reranker eval arm: BgeRerankerV2M3 quality + CPU latency (Phase E).

Ranking is the measured weakness of the committed baseline (MRR@10 0.927,
nDCG@10 0.944; five questions place first-relevant at rank 4-8) while
recall@10 is saturated at 1.000 — and production currently runs the STUB
reranker (`reranker_backend="disabled"`). `bge-reranker-v2-m3` is the
accepted ADR-0014 default model, already implemented and config-selectable;
under the 2026-06-11 models-freeze directive (current models, CPU + API
only), enabling it is the one ranking lever available.

DECISION RULE — frozen before measurement. Flip the production
`reranker_backend` default to "bge-reranker-v2-m3" iff BOTH:
  (a) quality: MRR@10 or nDCG@10 improves by >= +0.02 over the committed
      baseline (the C4 tolerance used as the significance bar), and
      recall@10 does not regress beyond the C4 tolerance;
  (b) latency: mean added search latency (reranker arm minus stub arm,
      same stack, same queries) <= 1000 ms/query on this hardware — keeps
      the measured P50 first-verified-token (3.11 s) inside the ADR-0017
      5 s bar with margin. Dev-Mac CPU is optimistic vs the VPS: any flip
      must be re-verified on the VPS before the SLA margin is relied upon.

Either outcome is recorded; a no-win leaves the config off (master plan
Phase E policy). The test asserts measurement integrity, not the outcome.
"""
from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.eval.conftest import EvalStack
from tests.eval.harness.ground_truth import resolve_expected_chunk_groups
from tests.eval.harness.loader import load_dataset
from tests.eval.harness.scorer import grouped_mrr_at_k, grouped_ndcg_at_k, grouped_recall_at_k

EVAL_DIR = Path(__file__).parent
HELDOUT_PATH = EVAL_DIR.parent.parent / "docs" / "uber-rag" / "eval" / "heldout-v1.yaml"
BASELINE_REPORT_PATH = EVAL_DIR / "reports" / "retrieval_baseline.json"
REPORT_PATH = EVAL_DIR / "reports" / "retrieval_reranker_arm.json"

K_VALUES = (5, 10, 20)
TOP_K = 20

QUALITY_LIFT_BAR = 0.02      # frozen: significance bar on MRR@10 / nDCG@10
RECALL_REGRESSION_BAR = 0.02  # frozen: C4 tolerance
LATENCY_OVERHEAD_BAR_MS = 1000.0  # frozen: mean added ms/query on this hardware


def _latency_stats(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)
    return {
        "mean_ms": round(statistics.fmean(ordered), 1),
        "p50_ms": round(ordered[len(ordered) // 2], 1),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 1),
    }


@pytest.mark.slow
def test_retrieval_reranker_arm(eval_stack: EvalStack):
    from app.schemas.search import SearchRequest

    dataset = load_dataset(HELDOUT_PATH)
    questions = [q for q in dataset.questions if q.evidence]
    assert len(questions) >= 60

    stub_service = eval_stack.search_service_parent_expansion
    reranker_service = eval_stack.search_service_real_reranker

    # Warmup both arms (loads reranker weights; embedder already warm).
    warmup = SearchRequest(query=questions[0].query, top_k=TOP_K)
    stub_service.search(context=eval_stack.context, payload=warmup)
    reranker_service.search(context=eval_stack.context, payload=warmup)

    per_question: list[dict] = []
    stub_times_ms: list[float] = []
    reranker_times_ms: list[float] = []
    for question in questions:
        groups = resolve_expected_chunk_groups(
            evidence=question.evidence,
            document_ids_by_slug=eval_stack.document_ids_by_slug,
        )
        assert groups, f"{question.id}: empty evidence groups"
        payload = SearchRequest(query=question.query, top_k=TOP_K)

        start = time.perf_counter()
        stub_service.search(context=eval_stack.context, payload=payload)
        stub_times_ms.append(1000 * (time.perf_counter() - start))

        start = time.perf_counter()
        response = reranker_service.search(context=eval_stack.context, payload=payload)
        reranker_times_ms.append(1000 * (time.perf_counter() - start))

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

    baseline = json.loads(BASELINE_REPORT_PATH.read_text(encoding="utf-8"))
    baseline_agg = baseline["aggregates"]
    lifts = {m: round(aggregates[m] - baseline_agg[m], 4) for m in metric_keys}

    stub_stats = _latency_stats(stub_times_ms)
    reranker_stats = _latency_stats(reranker_times_ms)
    mean_overhead_ms = round(reranker_stats["mean_ms"] - stub_stats["mean_ms"], 1)

    quality_pass = (
        (lifts["mrr@10"] >= QUALITY_LIFT_BAR or lifts["ndcg@10"] >= QUALITY_LIFT_BAR)
        and lifts["recall@10"] >= -RECALL_REGRESSION_BAR
    )
    latency_pass = mean_overhead_ms <= LATENCY_OVERHEAD_BAR_MS

    report = {
        "report": "retrieval_reranker_arm",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question_count": len(per_question),
        "retriever": {
            "dense": "BGE-M3 (real) via in-memory Qdrant",
            "lexical": "disabled (stub) — dense-only eval fixture",
            "reranker": "BAAI/bge-reranker-v2-m3 (real, CPU, plain transformers), candidates=20",
            "parent_expansion": "ENABLED (E1 shape: after-rerank, leaf ids, capped windows)",
            "top_k": TOP_K,
        },
        "latency": {
            "method": (
                "per-query wall time over the identical stack with stub vs real "
                "reranker, warmed; overhead = mean difference; dev-Mac CPU — "
                "optimistic vs the VPS, re-verify there before relying on SLA margin"
            ),
            "stub_arm": stub_stats,
            "reranker_arm": reranker_stats,
            "mean_overhead_ms": mean_overhead_ms,
        },
        "decision_rule": {
            "frozen": (
                "flip reranker_backend default iff (MRR@10 or nDCG@10 lift >= +0.02 "
                "AND recall@10 drop <= 0.02) AND mean overhead <= 1000 ms/query"
            ),
            "quality_pass": quality_pass,
            "latency_pass": latency_pass,
            "flip_default": quality_pass and latency_pass,
        },
        "baseline_reference": {m: baseline_agg[m] for m in metric_keys},
        "aggregates": aggregates,
        "lifts_vs_baseline": lifts,
        "by_language": by_language,
        "per_question": per_question,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nReranker arm written: {REPORT_PATH} ({len(per_question)} questions)")
    print("aggregate:", json.dumps(aggregates))
    print("lifts:", json.dumps(lifts))
    print("latency:", json.dumps(report["latency"]["stub_arm"]), "->", json.dumps(report["latency"]["reranker_arm"]), f"overhead {mean_overhead_ms} ms")
    print("decision:", json.dumps(report["decision_rule"]))

    # Measurement integrity only — the decision rule is applied to the report.
    assert len(per_question) >= 60
    assert aggregates["recall@20"] > 0.0