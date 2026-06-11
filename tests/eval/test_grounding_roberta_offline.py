"""ADR-0019 c3 path: MiniCheck-RoBERTa-Large measured offline (post-E0a).

The c1 re-measurement (2026-06-11) flipped criterion 1 to PASS for
MiniCheck-Flan-T5-Large, leaving the rejection standing on criterion 3 alone
(4553 ms/sentence CPU vs <= 500 ms). This measures the documented faster-CPU
fallback `lytang/MiniCheck-RoBERTa-Large` (MIT, 0.4B sequence classifier)
against all three frozen criteria WITHOUT regenerating answers:

- c1: re-scores the persisted answers + context blocks from
  `reports/grounding_vs_nli.json` (the D3/E0a run) — zero LLM calls.
- c2: the D4 canary fabrications/controls, grounding side swapped to RoBERTa.
- c3: mean per-sentence verify latency over the c1 loop, timed exactly like
  D3 (whole verify() call / sentence count, no warmup, lazy first-call load
  amortized across the run).

The test asserts measurement integrity, not the outcome — the frozen criteria
are applied to the committed report when updating ADR-0019.

Requires the ML stack and network for the first model download; no API key.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("transformers", reason="ML stack not installed")

from app.schemas.context import ContextBlock, ContextPayload
from app.services.answer_verifier_grounding import GroundingAnswerVerifier
from app.services.answer_verifier_nli import NliAnswerVerifier

from tests.eval.test_hallucination_canaries import (
    CANARIES,
    CONTRADICTION,
    CONTROLS,
    _payload_from,
)

EVAL_DIR = Path(__file__).parent
SOURCE_REPORT_PATH = EVAL_DIR / "reports" / "grounding_vs_nli.json"
REPORT_PATH = EVAL_DIR / "reports" / "grounding_roberta_offline.json"

MODEL_NAME = "lytang/MiniCheck-RoBERTa-Large"
GROUNDING_THRESHOLD = 0.5          # ADR-0019 production config
GROUNDING_RATIO_PRODUCTION = 0.0   # frozen


def _payload_from_persisted(block_texts: list[str], citation_ids: list[str | None]) -> ContextPayload:
    blocks = [
        ContextBlock(
            text=text,
            document_id=f"doc-{position}",
            document_title=f"Source {position}",
            chunk_id=citation_id,
            citation_id=citation_id,
            heading_path=[],
            rank=position,
        )
        for position, (text, citation_id) in enumerate(zip(block_texts, citation_ids), start=1)
    ]
    return ContextPayload(
        blocks=blocks,
        block_count=len(blocks),
        total_characters=sum(len(b.text) for b in blocks),
        truncated=False,
    )


def _faithfulness(summary) -> float:
    if summary.sentence_count == 0:
        return 0.0
    return summary.supported_sentence_count / summary.sentence_count


@pytest.mark.slow
def test_grounding_roberta_offline_measurement():
    source = json.loads(SOURCE_REPORT_PATH.read_text(encoding="utf-8"))
    answered = [q for q in source["per_question"] if q["status"] == "answered"]
    assert len(answered) >= 55, f"Persisted run has only {len(answered)} answered questions"

    grounding = GroundingAnswerVerifier(
        model_name=MODEL_NAME,
        threshold=GROUNDING_THRESHOLD,
        unsupported_ratio=GROUNDING_RATIO_PRODUCTION,
    )

    # --- c1 + c3: re-score the persisted answers, timed like D3 ---
    per_question: list[dict] = []
    sentence_times: list[float] = []
    for question in answered:
        payload = _payload_from_persisted(
            question["context_blocks"], question["context_citation_ids"]
        )
        start = time.perf_counter()
        summary = grounding.verify(answer_text=question["answer_text"], context_payload=payload)
        elapsed = time.perf_counter() - start
        if summary.sentence_count:
            sentence_times.append(elapsed / summary.sentence_count)

        per_question.append({
            "question_id": question["question_id"],
            "language": question["language"],
            "roberta": {
                "status": summary.status,
                "faithfulness": round(_faithfulness(summary), 4),
                "sentence_count": summary.sentence_count,
                "unsupported_sentences": [
                    s.sentence for s in summary.sentences if s.status == "unsupported"
                ],
            },
            "flan_t5_faithfulness_reference": question["grounding"]["faithfulness"],
        })

    def _mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    roberta_faith = _mean([q["roberta"]["faithfulness"] for q in per_question])
    mean_sentence_ms = round(1000 * _mean(sentence_times), 1)

    # --- c2: canary suite with the grounding side swapped to RoBERTa ---
    nli = NliAnswerVerifier(scoring_mode="not_contradicted", unsupported_ratio=0.2)
    canary_rows = []
    for doc, marker, claim in CANARIES:
        payload = _payload_from(doc, contains=marker)
        canary_rows.append({
            "kind": "fabrication",
            "doc": doc,
            "claim": claim,
            "nli_not_contradicted": nli.verify(answer_text=claim, context_payload=payload).status,
            "roberta": grounding.verify(answer_text=claim, context_payload=payload).status,
        })
    control_rows = []
    for doc, marker, claim in CONTROLS:
        payload = _payload_from(doc, contains=marker)
        control_rows.append({
            "kind": "paraphrase_control",
            "doc": doc,
            "claim": claim,
            "roberta": grounding.verify(answer_text=claim, context_payload=payload).status,
        })
    doc, marker, claim = CONTRADICTION
    contradiction_row = {
        "kind": "contradiction_control",
        "doc": doc,
        "claim": claim,
        "roberta": grounding.verify(
            answer_text=claim, context_payload=_payload_from(doc, contains=marker)
        ).status,
    }

    passed_by_nli = [r for r in canary_rows if r["nli_not_contradicted"] == "supported"]
    caught = [r for r in passed_by_nli if r["roberta"] == "unsupported"]
    catch_rate = len(caught) / len(passed_by_nli) if passed_by_nli else 1.0
    controls_supported = all(r["roberta"] == "supported" for r in control_rows)

    aggregates = {
        "answered_scored": len(per_question),
        "roberta": {
            "faithfulness": roberta_faith,
            "accept_rate_ratio_0_0": _mean([
                1.0 if q["roberta"]["status"] == "supported" else 0.0 for q in per_question
            ]),
            "mean_per_sentence_verify_ms": mean_sentence_ms,
            "canary_catch_rate_on_nli_blind_spot": round(catch_rate, 4),
            "nli_blind_spot_count": len(passed_by_nli),
            "paraphrase_controls_supported": controls_supported,
            "contradiction_control_rejected": contradiction_row["roberta"] == "unsupported",
        },
        "flan_t5_reference": {
            "faithfulness": source["aggregates"]["grounding"]["faithfulness"],
            "mean_per_sentence_verify_ms": source["aggregates"]["grounding"][
                "mean_per_sentence_verify_ms"
            ],
        },
        "adr_0019_criteria": {
            "c1_faithfulness_ge_0_85": roberta_faith >= 0.85,
            "c2_canary_catch_ge_0_80": catch_rate >= 0.80,
            "c3_mean_sentence_verify_le_500ms": mean_sentence_ms <= 500.0,
        },
    }

    report = {
        "report": "grounding_roberta_offline",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL_NAME,
        "method": (
            "offline re-scoring of the persisted answers from grounding_vs_nli.json "
            "(generated once by ppq Llama 3.3 70B post-E0a); canaries from the D4 "
            "suite; latency timed as whole verify() / sentence count, no warmup "
            "(D3 method)"
        ),
        "config": {
            "threshold": GROUNDING_THRESHOLD,
            "unsupported_ratio": GROUNDING_RATIO_PRODUCTION,
            "max_input_length": 512,
        },
        "aggregates": aggregates,
        "canaries": canary_rows + control_rows + [contradiction_row],
        "per_question": per_question,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nRoBERTa offline report written: {REPORT_PATH}")
    print(json.dumps(aggregates, indent=2))

    # Measurement integrity (outcome is applied to the ADR, not asserted here).
    assert len(passed_by_nli) >= 5, "NLI blind spot vanished — canary premise broken"
    assert len(per_question) >= 55
