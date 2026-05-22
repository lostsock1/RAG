"""Step 7: NLI verifier faithfulness measurement on 15 answered questions.

Uses the NLI cross-encoder verifier instead of the substring verifier.
The NLI verifier correctly handles paraphrased content by using natural
language inference rather than exact substring matching.

Configurable via environment variables:
  NLI_THRESHOLD       support score threshold (default 0.5)
  SCORING_MODE        "entailment" or "not_contradicted" (default "not_contradicted")
  UNSUPPORTED_RATIO   max fraction of unsupported sentences allowed (default 0.2)

Target: >= 0.85 faithfulness.
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
ANSWERED_IDS = {
    "h01", "h04", "h10", "h12", "h13",
    "h16", "h19", "h25", "h29", "h31",
    "n03", "n06", "n12", "n15", "n19",
}


def _make_zero_faithfulness_verification() -> object:
    """Create a minimal verification object for unanswered / no-evidence cases."""
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
def test_nli_faithfulness(eval_stack: EvalStack, monkeypatch):
    """Measure faithfulness with NLI verifier on 15 answered questions."""
    api_key = os.environ.get("PPQ_API_KEY")
    if not api_key:
        pytest.skip("PPQ_API_KEY not set — skipping real LLM NLI measurement")

    nli_threshold = float(os.environ.get("NLI_THRESHOLD", "0.5"))
    scoring_mode = os.environ.get("SCORING_MODE", "not_contradicted")
    unsupported_ratio = float(os.environ.get("UNSUPPORTED_RATIO", "0.2"))

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

    # -- 2. Swap in NLI verifier with configurable params ---------------
    from app.services.answer_verifier_nli import NliAnswerVerifier

    nli_verifier = NliAnswerVerifier(
        entailment_threshold=nli_threshold,
        scoring_mode=scoring_mode,
        unsupported_ratio=unsupported_ratio,
    )
    eval_stack.chat_service._answer_verifier = nli_verifier

    # -- 3. Disable audit writes (no DB table in eval fixture) ----------
    monkeypatch.setattr(
        "app.services.chat_service.write_audit_event",
        lambda *a, **kw: None,
    )

    # -- 4. Load dataset and filter to our 15 answered questions -------
    dataset = load_dataset(HELDOUT_PATH)
    answered_questions = [q for q in dataset.questions if q.id in ANSWERED_IDS]
    assert len(answered_questions) == 15, (
        f"Expected 15 questions, got {len(answered_questions)}. "
        f"Found IDs: {[q.id for q in answered_questions]}"
    )

    # -- 5. Run through harness ----------------------------------------
    runner = EvalRunner(
        chat_service=eval_stack.chat_service,
        dataset=dataset,
        request_context=eval_stack.context,
    )

    results = []
    for question in answered_questions:
        result = runner.run(questions=[question])[0]
        results.append(result)
        time.sleep(1)  # rate-limit guard

    # -- 6. Score each result ------------------------------------------
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
        if verification and verification.sentence_count > 0:
            print(
                f"  Verification: {verification.supported_sentence_count}/{verification.sentence_count} "
                f"supported, status={verification.status}"
            )

    # -- 7. Aggregate --------------------------------------------------
    report = aggregate(scores)
    print(f"\n{'=' * 60}")
    print(f"NLI FAITHFULNESS REPORT")
    print(f"{'=' * 60}")
    print(f"Scoring mode:              {scoring_mode}")
    print(f"NLI threshold:             {nli_threshold}")
    print(f"Unsupported ratio:         {unsupported_ratio}")
    print(f"Total questions:           {report.total_questions}")
    print(f"Faithfulness:              {report.faithfulness:.3f}")
    print(f"Answer contains pass rate: {report.answer_contains_pass_rate:.3f}")
    print(f"Answer absent pass rate:   {report.answer_absent_pass_rate:.3f}")
    print(f"{'=' * 60}")

    # -- 8. Identify low-faithfulness questions for diagnosis ----------
    low_faith = [s for s in scores if s.faithfulness < 0.5]
    if low_faith:
        print(f"\nQuestions with faithfulness < 0.5 ({len(low_faith)}):")
        for s in low_faith:
            print(f"  - {s.question_id}: faithfulness={s.faithfulness:.2f}")

    # -- 9. Assertion --------------------------------------------------
    assert report.faithfulness >= 0.85, (
        f"NLI faithfulness {report.faithfulness:.3f} is below 0.85 target. "
        f"Try adjusting NLI_THRESHOLD, SCORING_MODE, or UNSUPPORTED_RATIO env vars. "
        f"Current: mode={scoring_mode}, threshold={nli_threshold}, ratio={unsupported_ratio}"
    )
