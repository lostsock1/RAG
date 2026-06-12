"""E3 eval arm: query understanding (multi-query / decompose / both) — ADR-0021.

Query understanding does NOT change ingestion, so all arms reuse the
session-scoped eval stack (same corpus, same index, same embedder) and only
compose retriever variants over its shared components. Lifts are computed
against the COMMITTED baseline report; a no-understanding control arm on the
same stack provides the paired latency reference and the candidate-pool
comparison for the positive control.

DECISION RULE — frozen in ADR-0021 BEFORE measurement: flip iff (overall
MRR@10 or nDCG@10 lift >= +0.02) AND (recall@10 drop <= 0.02) AND (added
gated-route latency <= 700 ms at P50). Subset lifts are recorded, never
deciding. Cheaper passing arm wins ties unless a costlier arm adds >= +0.02.
decompose with zero triggers is recorded NOT EXERCISED — distinct from
"no win".

POSITIVE CONTROLS (E1/E2 lesson): multi_query must fire on every gated
question and produce >= 1 paraphrase on average AND the result set must
differ from the control for > 0 questions; decompose records its trigger
count. A silently inert arm must not reproduce the baseline as "no win".

multi_query/both make ONE real ppq call per question (~3 s x 60 x 2 arms
~= 6-7 min). Requires PPQ_API_KEY; skips otherwise.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.eval.conftest import EvalStack, _CountingSearchSourcesRepo
from tests.eval.harness.ground_truth import resolve_expected_chunk_groups
from tests.eval.harness.loader import load_dataset
from tests.eval.harness.scorer import grouped_mrr_at_k, grouped_ndcg_at_k, grouped_recall_at_k

EVAL_DIR = Path(__file__).parent
HELDOUT_PATH = EVAL_DIR.parent.parent / "docs" / "uber-rag" / "eval" / "heldout-v1.yaml"
BASELINE_REPORT_PATH = EVAL_DIR / "reports" / "retrieval_baseline.json"
REPORT_PATH = EVAL_DIR / "reports" / "retrieval_query_understanding.json"

K_VALUES = (5, 10, 20)
TOP_K = 20

QUALITY_LIFT_BAR = 0.02       # frozen (ADR-0021)
RECALL_REGRESSION_BAR = 0.02  # frozen (ADR-0021)
LATENCY_P50_BAR_MS = 700.0    # frozen (ADR-0021): added P50 on gated routes
TIE_BREAK_EXTRA_LIFT = 0.02   # frozen (ADR-0021)

METRIC_KEYS = [f"recall@{k}" for k in K_VALUES] + [f"ndcg@{k}" for k in K_VALUES] + ["mrr@10"]


class _CountingUnderstander:
    """Positive-control wrapper: records every expansion the arm produced."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls = 0
        self.expansions: list[list[str]] = []

    def expand(self, query: str) -> list[str]:
        result = self._inner.expand(query)
        self.calls += 1
        self.expansions.append(list(result))
        return result


def _build_service(components, *, understander=None):
    from app.services.retrieval.hybrid_retriever import HybridSearchRetriever
    from app.services.retrieval.reranker import StubReranker
    from app.services.retrieval.router import QueryRouter
    from app.services.retrieval.search_service import SearchService

    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=components["opensearch_retriever"],
        vector_retriever=components["qdrant_retriever"],
        query_embedder=components["query_embedder"],
        search_sources_repository=_CountingSearchSourcesRepo(),
        reranker=StubReranker(),
        rerank_candidate_limit=20,
        parent_expansion_enabled=True,
        query_understander=understander,
    )
    return SearchService(retriever=retriever)


def _latency_stats(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)
    return {
        "mean_ms": round(statistics.fmean(ordered), 1),
        "p50_ms": round(ordered[len(ordered) // 2], 1),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 1),
    }


def _aggregate(per_question: list[dict]) -> dict:
    def mean(metric: str) -> float:
        return round(sum(r["metrics"][metric] for r in per_question) / len(per_question), 4)

    return {m: mean(m) for m in METRIC_KEYS}


def _by_subset(per_question: list[dict], key: str) -> dict:
    out: dict[str, dict] = {}
    for value in sorted({q[key] for q in per_question}):
        rows = [q for q in per_question if q[key] == value]
        out[value] = {"question_count": len(rows), **_aggregate(rows)}
    return out


def _quality_pass(lifts: dict) -> bool:
    return (
        lifts["mrr@10"] >= QUALITY_LIFT_BAR or lifts["ndcg@10"] >= QUALITY_LIFT_BAR
    ) and lifts["recall@10"] >= -RECALL_REGRESSION_BAR


@pytest.mark.slow
def test_retrieval_query_understanding_arms(eval_stack: EvalStack):
    from app.schemas.search import SearchRequest
    from app.services.retrieval.query_understanding import (
        CompositeQueryUnderstander,
        HeuristicQueryDecomposer,
        LlmMultiQueryExpander,
    )

    api_key = os.environ.get("PPQ_API_KEY")
    if not api_key:
        pytest.skip("PPQ_API_KEY not set — multi_query/both arms cannot run")

    dataset = load_dataset(HELDOUT_PATH)
    questions = [q for q in dataset.questions if q.evidence]
    assert len(questions) >= 60

    baseline_agg = json.loads(BASELINE_REPORT_PATH.read_text(encoding="utf-8"))["aggregates"]
    components = eval_stack.retrieval_components
    assert components is not None

    def _make_llm_expander():
        return LlmMultiQueryExpander(
            base_url="https://api.ppq.ai/v1",
            api_key=api_key,
            model_name="meta-llama/Llama-3.3-70B-Instruct",
            max_expansions=3,
            max_output_tokens=256,
        )

    control_service = _build_service(components)
    arm_specs = {
        "decompose": _CountingUnderstander(HeuristicQueryDecomposer()),
        "multi_query": _CountingUnderstander(_make_llm_expander()),
        "both": _CountingUnderstander(
            CompositeQueryUnderstander(
                understanders=[HeuristicQueryDecomposer(), _make_llm_expander()],
                max_expansions=3,
            )
        ),
    }
    arm_services = {
        name: _build_service(components, understander=understander)
        for name, understander in arm_specs.items()
    }

    # Warmup (embedder warm from stack build; warms retrieval path + weights).
    warmup = SearchRequest(query=questions[0].query, top_k=TOP_K)
    control_service.search(context=eval_stack.context, payload=warmup)

    control_times_ms: list[float] = []
    control_ids: dict[str, list[str]] = {}
    groups_by_question: dict[str, list[set[str]]] = {}
    for question in questions:
        groups = resolve_expected_chunk_groups(
            evidence=question.evidence,
            document_ids_by_slug=eval_stack.document_ids_by_slug,
        )
        assert groups, f"{question.id}: empty evidence groups"
        groups_by_question[question.id] = groups
        payload = SearchRequest(query=question.query, top_k=TOP_K)
        start = time.perf_counter()
        response = control_service.search(context=eval_stack.context, payload=payload)
        control_times_ms.append(1000 * (time.perf_counter() - start))
        control_ids[question.id] = [item.chunk_id for item in response.items if item.chunk_id]

    arms: dict[str, dict] = {}
    for arm_name, service in arm_services.items():
        counting = arm_specs[arm_name]
        per_question: list[dict] = []
        times_ms: list[float] = []
        pool_differs = 0
        for question in questions:
            payload = SearchRequest(query=question.query, top_k=TOP_K)
            start = time.perf_counter()
            response = service.search(context=eval_stack.context, payload=payload)
            times_ms.append(1000 * (time.perf_counter() - start))
            ranked_ids = [item.chunk_id for item in response.items if item.chunk_id]
            if set(ranked_ids) != set(control_ids[question.id]):
                pool_differs += 1
            metrics = {}
            groups = groups_by_question[question.id]
            for k in K_VALUES:
                metrics[f"recall@{k}"] = round(grouped_recall_at_k(ranked_ids, groups, k), 4)
                metrics[f"ndcg@{k}"] = round(grouped_ndcg_at_k(ranked_ids, groups, k), 4)
            metrics["mrr@10"] = round(grouped_mrr_at_k(ranked_ids, groups, 10), 4)
            per_question.append(
                {
                    "question_id": question.id,
                    "type": question.type,
                    "language": question.language,
                    "metrics": metrics,
                }
            )

        expansion_counts = [len(e) for e in counting.expansions]
        triggered = sum(1 for count in expansion_counts if count > 0)
        aggregates = _aggregate(per_question)
        lifts = {m: round(aggregates[m] - baseline_agg[m], 4) for m in METRIC_KEYS}
        arm_stats = _latency_stats(times_ms)
        control_stats = _latency_stats(control_times_ms)
        added_p50 = round(arm_stats["p50_ms"] - control_stats["p50_ms"], 1)

        exercised = triggered > 0
        quality = _quality_pass(lifts) if exercised else False
        latency_ok = added_p50 <= LATENCY_P50_BAR_MS

        arms[arm_name] = {
            "positive_control": {
                "expander_calls": counting.calls,
                "questions_triggering_expansion": triggered,
                "total_expansions": sum(expansion_counts),
                "mean_expansions_per_question": round(
                    sum(expansion_counts) / max(len(expansion_counts), 1), 2
                ),
                "result_set_differs_from_control": pool_differs,
                "exercised": exercised,
            },
            "aggregates": aggregates,
            "lifts_vs_baseline": lifts,
            "by_type": _by_subset(per_question, "type"),
            "by_language": _by_subset(per_question, "language"),
            "latency": {
                "control": control_stats,
                "arm": arm_stats,
                "added_p50_ms": added_p50,
                "added_mean_ms": round(arm_stats["mean_ms"] - control_stats["mean_ms"], 1),
            },
            "quality_pass": quality,
            "latency_pass": latency_ok,
            "verdict": (
                "not_exercised"
                if not exercised
                else ("pass" if (quality and latency_ok) else "no_win")
            ),
            "per_question": per_question,
        }
        print(f"\n[{arm_name}] control={arms[arm_name]['positive_control']}")
        print(f"[{arm_name}] lifts={json.dumps(lifts)} latency_added_p50={added_p50}ms")
        print(f"[{arm_name}] verdict={arms[arm_name]['verdict']}")

    # POSITIVE CONTROLS (frozen): multi_query must actually expand and perturb.
    mq = arms["multi_query"]["positive_control"]
    assert mq["expander_calls"] == len(questions)
    assert mq["mean_expansions_per_question"] >= 1.0, mq
    assert mq["result_set_differs_from_control"] > 0, mq
    # decompose: trigger count is recorded; zero triggers => NOT EXERCISED is
    # a legal, explicitly-distinct outcome (no assertion that it fired).

    passing = [name for name, arm in arms.items() if arm["verdict"] == "pass"]
    cost_order = ["decompose", "multi_query", "both"]
    adopt = None
    if passing:
        cheapest = min(passing, key=cost_order.index)
        adopt = cheapest
        for costlier in passing:
            if cost_order.index(costlier) <= cost_order.index(cheapest):
                continue
            extra_mrr = (
                arms[costlier]["lifts_vs_baseline"]["mrr@10"]
                - arms[cheapest]["lifts_vs_baseline"]["mrr@10"]
            )
            extra_ndcg = (
                arms[costlier]["lifts_vs_baseline"]["ndcg@10"]
                - arms[cheapest]["lifts_vs_baseline"]["ndcg@10"]
            )
            if extra_mrr >= TIE_BREAK_EXTRA_LIFT or extra_ndcg >= TIE_BREAK_EXTRA_LIFT:
                adopt = costlier

    report = {
        "report": "retrieval_query_understanding",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question_count": len(questions),
        "rig": {
            "stack": "session eval_stack (same corpus/index/embedder; no re-ingestion needed)",
            "shape": "parent expansion ON, stub reranker, dense-only lexical stub, top_k=20",
            "control": "identical retriever without an understander (paired latency + pool diff)",
            "llm": "ppq meta-llama/Llama-3.3-70B-Instruct, 1 paraphrase call per gated search",
        },
        "decision_rule": {
            "frozen": (
                "ADR-0021: flip iff (overall MRR@10 or nDCG@10 lift >= +0.02) AND "
                "(recall@10 drop <= 0.02) AND (added gated-route P50 <= 700 ms); "
                "subset lifts record-only; cheaper passing arm wins unless a "
                "costlier passing arm adds >= +0.02; decompose zero-trigger = "
                "not_exercised, distinct from no_win"
            ),
            "verdicts": {name: arm["verdict"] for name, arm in arms.items()},
            "adopt_arm": adopt,
        },
        "baseline_reference": {m: baseline_agg[m] for m in METRIC_KEYS},
        "arms": arms,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nQuery-understanding arms written: {REPORT_PATH}")
    print("decision:", json.dumps(report["decision_rule"]["verdicts"]), "adopt:", adopt)

    # Measurement integrity only — the frozen rule is applied to the report.
    for arm_name, arm in arms.items():
        assert len(arm["per_question"]) >= 60, arm_name
        assert arm["aggregates"]["recall@20"] > 0.0, arm_name
