"""C3: retrieval-only quality measurement — no LLM, no verifier.

Runs every span-anchored question through the hybrid search path (real BGE-M3
dense retrieval against the in-memory Qdrant fixture), resolves the expected
chunk IDs from evidence spans, and scores recall@k / MRR / nDCG. Writes the
canonical baseline report consumed by the CI advisory gate (C4).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.eval.conftest import EvalStack
from tests.eval.harness.ground_truth import resolve_expected_chunk_groups
from tests.eval.harness.loader import load_dataset
from tests.eval.harness.scorer import grouped_mrr_at_k, grouped_ndcg_at_k, grouped_recall_at_k

EVAL_DIR = Path(__file__).parent
HELDOUT_PATH = EVAL_DIR.parent.parent / "docs" / "uber-rag" / "eval" / "heldout-v1.yaml"
REPORT_PATH = EVAL_DIR / "reports" / "retrieval_baseline.json"

K_VALUES = (5, 10, 20)
TOP_K = 20


@pytest.mark.slow
def test_retrieval_quality_baseline(eval_stack: EvalStack):
    """Measure retrieval quality on all evidence-backed questions and write
    the canonical baseline report."""
    from app.schemas.search import SearchRequest

    dataset = load_dataset(HELDOUT_PATH)
    questions = [q for q in dataset.questions if q.evidence]
    assert len(questions) >= 60, (
        f"Phase C exit criterion: expected >= 60 evidence-backed questions, got {len(questions)}"
    )

    per_question: list[dict] = []
    for question in questions:
        groups = resolve_expected_chunk_groups(
            evidence=question.evidence,
            document_ids_by_slug=eval_stack.document_ids_by_slug,
        )
        assert groups, f"{question.id}: empty evidence groups"

        response = eval_stack.search_service.search(
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
            "expected_chunk_count": sum(len(g) for g in groups),
            "retrieved_count": len(ranked_ids),
            "metrics": metrics,
            "top_5_chunk_ids": ranked_ids[:5],
        })

    def _mean_over(rows: list[dict], metric: str) -> float:
        return round(sum(r["metrics"][metric] for r in rows) / len(rows), 4) if rows else 0.0

    metric_keys = [f"recall@{k}" for k in K_VALUES] + [f"ndcg@{k}" for k in K_VALUES] + ["mrr@10"]
    aggregates = {m: _mean_over(per_question, m) for m in metric_keys}

    # Per-language breakdown (multilingual subset is a Phase C exit deliverable).
    by_language: dict[str, dict] = {}
    languages = sorted({q["language"] for q in per_question})
    for lang in languages:
        rows = [q for q in per_question if q["language"] == lang]
        by_language[lang] = {
            "question_count": len(rows),
            **{m: _mean_over(rows, m) for m in metric_keys},
        }

    report = {
        "report": "retrieval_baseline",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question_count": len(per_question),
        "retriever": {
            "dense": "BGE-M3 (real) via in-memory Qdrant",
            "lexical": "disabled (stub) — dense-only eval fixture",
            "reranker": "stub (pass-through)",
            "parent_expansion": "disabled in eval fixture",
            "top_k": TOP_K,
        },
        "ground_truth": "span-anchored (heldout-v1 evidence blocks, resolved at runtime)",
        "metrics_semantics": (
            "per-span equivalence groups: a span counts as retrieved when ANY "
            "chunk containing it is ranked (leaf/parent duplication is not "
            "penalized; duplicate members of a satisfied group earn nothing)"
        ),
        "aggregates": aggregates,
        "by_language": by_language,
        "per_question": per_question,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nRetrieval baseline written: {REPORT_PATH} ({len(per_question)} questions)")
    print("aggregate:", json.dumps(aggregates))
    print("by language:", json.dumps({k: {m: v[m] for m in ("question_count", "recall@10", "mrr@10")} for k, v in by_language.items()}))

    # German and Portuguese must both be represented (multilingual exit deliverable).
    assert by_language.get("de", {}).get("question_count", 0) >= 2
    assert by_language.get("pt", {}).get("question_count", 0) >= 2

    # Sanity floor, not a tuned threshold: dense retrieval must find *something*.
    assert aggregates["recall@20"] > 0.0
