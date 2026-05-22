"""Eval: negative-answer compliance against populated corpus.

Primary Phase 4 measurement: runs the 23 negative questions against the
eval_stack fixture with real BGE-M3 retrieval and populated fixture corpus.

This is the honest measurement — retrieval may pull topically-similar chunks
for negative questions, and the system must still return not_enough_evidence.

Phase 4 exit criterion: negative_answer_compliance >= 0.90 on populated corpus.
(Empty-corpus stub compliance is 1.00 — see
 apps/api/app/tests/integration/test_negative_subset_compliance.py)
"""
from __future__ import annotations

import pytest

from tests.eval.conftest import EvalStack
from tests.eval.harness.loader import load_dataset, filter_questions
from tests.eval.harness.runner import EvalRunner
from tests.eval.harness.scorer import score_negative, aggregate

EVAL_DIR = __import__("pathlib").Path(__file__).parent
HELDOUT_PATH = EVAL_DIR.parent.parent / "docs" / "uber-rag" / "eval" / "heldout-v1.yaml"


@pytest.mark.slow
def test_negative_compliance_populated_corpus(eval_stack: EvalStack, monkeypatch):
    """Negative-answer compliance against populated corpus must be >= 0.90.

    The eval_stack has real BGE-M3 retrieval with 8 fixture documents indexed.
    Negative questions are about topics NOT in the corpus — the system should
    return not_enough_evidence even when retrieval finds topically-similar chunks.
    """
    # Disable audit writes (no DB table in eval fixture)
    monkeypatch.setattr(
        "app.services.chat_service.write_audit_event",
        lambda *a, **kw: None,
    )

    dataset = load_dataset(HELDOUT_PATH)
    negative_questions = filter_questions(dataset.questions, type="negative")

    assert len(negative_questions) >= 20, (
        f"Expected at least 20 negative questions, found {len(negative_questions)}"
    )

    runner = EvalRunner(
        chat_service=eval_stack.chat_service,
        dataset=dataset,
        request_context=eval_stack.context,
    )
    results = runner.run(questions=negative_questions)

    scores = [score_negative(q, r.response) for q, r in zip(negative_questions, results)]
    report = aggregate(scores)

    # Report per-question failures for diagnosis
    failures = [s for s in scores if not s.compliant]
    if failures:
        print(f"\nNegative compliance failures ({len(failures)}/{len(scores)}):")
        for s in failures:
            q = next(q for q in negative_questions if q.id == s.question_id)
            print(f"  - {s.question_id}: query='{q.query[:80]}'")

    print(f"\n{'=' * 60}")
    print(f"NEGATIVE COMPLIANCE — POPULATED CORPUS")
    print(f"{'=' * 60}")
    print(f"Total negative questions: {len(scores)}")
    print(f"Compliance:               {report.negative_answer_compliance:.2f}")
    print(f"Failures:                  {len(failures)}")
    print(f"{'=' * 60}")

    assert report.negative_answer_compliance >= 0.90, (
        f"Negative compliance {report.negative_answer_compliance:.2f} on populated corpus "
        f"is below 0.90 threshold. "
        f"Failures: {[s.question_id for s in failures]}"
    )
