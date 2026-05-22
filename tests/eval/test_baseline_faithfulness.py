"""Step 5: Baseline faithfulness measurement on 15 answered questions.

Swaps the StubLlmBackend for a real PpqLlmBackend, runs 15 answered
questions through the full retrieval + generation + verification pipeline,
and measures aggregate faithfulness with the substring verifier.

Baseline threshold: >= 0.02 (actual baseline measured at 0.033).
Target for Step 7:  >= 0.85.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from tests.eval.conftest import EvalStack
from tests.eval.harness.loader import load_dataset
from tests.eval.harness.runner import EvalRunner
from tests.eval.harness.scorer import AnsweredScore, score_answered, aggregate

EVAL_DIR = Path(__file__).parent
HELDOUT_PATH = EVAL_DIR.parent.parent / "docs" / "uber-rag" / "eval" / "heldout-v1.yaml"

# The 15 answered questions that have ground-truth in the fixture corpus.
# Selected to cover: definitions (h01, h04, h10, h12, h13),
# exact lookups (h16, h19, h25), formulas (h29, h31),
# needles (n03, n06, n12, n15, n19).
ANSWERED_IDS = {
    "h01", "h04", "h10", "h12", "h13",
    "h16", "h19", "h25", "h29", "h31",
    "n03", "n06", "n12", "n15", "n19",
}


def _make_zero_faithfulness_verification() -> object:
    """Create a minimal verification object for unanswered / no-evidence cases.

    When the system returns ``not_enough_evidence``, the verification field
    may be ``None``.  ``score_answered`` expects ``.sentence_count`` and
    ``.supported_sentence_count``, so we provide a synthetic object with
    zero counts.
    """
    from app.schemas.verification import VerificationSummary

    return VerificationSummary(
        status="unsupported",
        sentence_count=0,
        supported_sentence_count=0,
        unsupported_sentence_count=0,
        insufficient_evidence_sentence_count=0,
        sentences=[],
    )


@pytest.mark.slow
def test_baseline_faithfulness_substring(eval_stack: EvalStack, monkeypatch):
    """Measure baseline faithfulness with substring verifier on 15 answered questions."""
    api_key = os.environ.get("PPQ_API_KEY")
    if not api_key:
        pytest.skip("PPQ_API_KEY not set — skipping real LLM baseline measurement")

    # -- 1. Swap in real LLM backend -----------------------------------
    from app.services.llm_backend import PpqLlmBackend

    real_llm = PpqLlmBackend(
        base_url="https://api.ppq.ai/v1",
        api_key=api_key,
        model_name="meta-llama/Llama-3.3-70B-Instruct",
        default_temperature=0.0,
        default_max_output_tokens=512,
    )
    eval_stack.chat_service._llm_backend = real_llm

    # -- 2. Disable audit writes (no DB table in eval fixture) ----------
    monkeypatch.setattr(
        "app.services.chat_service.write_audit_event",
        lambda *a, **kw: None,
    )

    # -- 3. Load dataset and filter to our 15 answered questions -------
    dataset = load_dataset(HELDOUT_PATH)
    answered_questions = [q for q in dataset.questions if q.id in ANSWERED_IDS]
    assert len(answered_questions) == 15, (
        f"Expected 15 questions, got {len(answered_questions)}. "
        f"Found IDs: {[q.id for q in answered_questions]}"
    )

    # -- 4. Run through harness ----------------------------------------
    runner = EvalRunner(
        chat_service=eval_stack.chat_service,
        dataset=dataset,
        request_context=eval_stack.context,
    )

    # Run one at a time with a small delay to avoid rate-limiting
    results = []
    for question in answered_questions:
        result = runner.run(questions=[question])[0]
        results.append(result)
        time.sleep(1)  # rate-limit guard

    # -- 5. Score each result ------------------------------------------
    scores: list[AnsweredScore] = []
    for result in results:
        question = next(q for q in answered_questions if q.id == result.question_id)
        verification = result.verification
        if verification is None:
            verification = _make_zero_faithfulness_verification()

        score = score_answered(
            question=question,
            response=result.response,
            verification=verification,
        )
        scores.append(score)

        # Per-question detail
        answer_preview = result.response.answer_text[:200].replace("\n", " ")
        print(
            f"\n{question.id} ({question.type}): "
            f"faithfulness={score.faithfulness:.2f} "
            f"contains_rate={score.answer_contains_pass_rate:.2f} "
            f"absent_fail={score.answer_absent_fail} "
            f"status_match={score.status_match}"
        )
        print(f"  Answer: {answer_preview}")

    # -- 6. Aggregate --------------------------------------------------
    report = aggregate(scores)
    print(f"\n{'=' * 60}")
    print(f"BASELINE FAITHFULNESS REPORT")
    print(f"{'=' * 60}")
    print(f"Total questions:           {report.total_questions}")
    print(f"Faithfulness:              {report.faithfulness:.3f}")
    print(f"Answer contains pass rate: {report.answer_contains_pass_rate:.3f}")
    print(f"Answer absent pass rate:   {report.answer_absent_pass_rate:.3f}")
    print(f"{'=' * 60}")

    # -- 7. Identify zero-faithfulness questions for Step 7 diagnosis ---
    zero_faith = [s for s in scores if s.faithfulness == 0.0]
    if zero_faith:
        print(f"\nQuestions with 0.0 faithfulness ({len(zero_faith)}):")
        for s in zero_faith:
            print(f"  - {s.question_id}")

    # -- 8. Baseline assertion -----------------------------------------
    # NOTE: Baseline measured at 0.033 on 2026-05-22. The substring verifier
    # is extremely strict (requires entire sentences as verbatim substrings of
    # context blocks). Most LLM answers get downgraded to "not_enough_evidence"
    # because even one unsupported sentence causes overall verification failure.
    # Step 7 will improve the pipeline to reach >= 0.85.
    assert report.faithfulness >= 0.02, (
        f"Baseline faithfulness {report.faithfulness:.3f} is below 0.02 threshold. "
        f"Regression detected — investigate retrieval or verification pipeline."
    )
