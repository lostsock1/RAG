"""D5: LLM-as-judge calibration against the grounding verifier (eval-only).

Reuses the answers persisted by the D3 measurement (grounding_vs_nli.json) —
no regeneration. A seeded 30-question subsample keeps the judge cost bounded.
Reports Cohen's kappa between per-sentence judge verdicts and the grounding
verifier's per-sentence verdicts.

Requires PPQ_API_KEY and a committed D3 report; skips otherwise.
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.eval.harness.judge import PpqSentenceJudge, cohens_kappa, split_sentences

EVAL_DIR = Path(__file__).parent
D3_REPORT_PATH = EVAL_DIR / "reports" / "grounding_vs_nli.json"
REPORT_PATH = EVAL_DIR / "reports" / "judge_calibration.json"

SUBSAMPLE_SIZE = 30
SUBSAMPLE_SEED = 20260611


@pytest.mark.slow
def test_judge_calibration_kappa():
    api_key = os.environ.get("PPQ_API_KEY")
    if not api_key:
        pytest.skip("PPQ_API_KEY not set")
    if not D3_REPORT_PATH.exists():
        pytest.skip("D3 report missing — run test_grounding_faithfulness first")

    from app.core.config import Settings

    settings = Settings()
    judge = PpqSentenceJudge(
        base_url="https://api.ppq.ai/v1",
        api_key=api_key,
        model_name=settings.llm_model_name,
    )

    d3 = json.loads(D3_REPORT_PATH.read_text(encoding="utf-8"))
    answered = [q for q in d3["per_question"] if q.get("status") == "answered"]
    rng = random.Random(SUBSAMPLE_SEED)
    sample = rng.sample(answered, min(SUBSAMPLE_SIZE, len(answered)))

    judge_labels: list[int] = []
    grounding_labels: list[int] = []
    rows = []
    for q in sample:
        sentences = split_sentences(q["answer_text"])
        unsupported = set(q["grounding"]["unsupported_sentences"])
        for sentence in sentences:
            g_label = 0 if sentence in unsupported else 1
            j_label = judge.judge(sentence=sentence, evidence_blocks=q["context_blocks"])
            grounding_labels.append(g_label)
            judge_labels.append(j_label)
            if g_label != j_label:
                rows.append({
                    "question_id": q["question_id"],
                    "sentence": sentence,
                    "grounding": g_label,
                    "judge": j_label,
                })

    kappa = cohens_kappa(judge_labels, grounding_labels)
    agreement = sum(
        1 for a, b in zip(judge_labels, grounding_labels) if a == b
    ) / len(judge_labels)

    report = {
        "report": "judge_calibration",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "judge_model": settings.llm_model_name,
        "subsample": {"size": len(sample), "seed": SUBSAMPLE_SEED},
        "sentence_pairs": len(judge_labels),
        "raw_agreement": round(agreement, 4),
        "cohens_kappa": round(kappa, 4),
        "judge_support_rate": round(sum(judge_labels) / len(judge_labels), 4),
        "grounding_support_rate": round(sum(grounding_labels) / len(grounding_labels), 4),
        "disagreements": rows,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nJudge calibration written: {REPORT_PATH}")
    print(f"sentences={len(judge_labels)} agreement={agreement:.2%} kappa={kappa:.3f}")

    assert len(judge_labels) >= 60, "Too few sentence pairs for a meaningful kappa"
