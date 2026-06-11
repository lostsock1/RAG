"""D3: grounding vs not_contradicted, measured on identical answers (ADR-0019).

Generates one answer per evidence-backed question with the production LLM
(ppq Llama 3.3 70B), then scores the SAME answer + context with both
verifiers. Persists everything (including answers and context block texts) so
D5's LLM-judge calibration can reuse the run without regenerating.

The test asserts measurement integrity, not the outcome — ADR-0019's frozen
criteria are applied to the committed report when closing the ADR.

Requires PPQ_API_KEY (skips otherwise) and both verifier models.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("transformers", reason="ML stack not installed")

from tests.eval.conftest import EvalStack
from tests.eval.harness.loader import load_dataset

EVAL_DIR = Path(__file__).parent
HELDOUT_PATH = EVAL_DIR.parent.parent / "docs" / "uber-rag" / "eval" / "heldout-v1.yaml"
REPORT_PATH = EVAL_DIR / "reports" / "grounding_vs_nli.json"

GROUNDING_THRESHOLD = 0.5          # ADR-0019 production config
GROUNDING_RATIO_PRODUCTION = 0.0   # frozen
GROUNDING_RATIO_SENSITIVITY = 0.2  # reported, not production


def _faithfulness(summary) -> float:
    if summary.sentence_count == 0:
        return 0.0
    return summary.supported_sentence_count / summary.sentence_count


@pytest.mark.slow
def test_grounding_vs_nli_measurement(eval_stack: EvalStack):
    api_key = os.environ.get("PPQ_API_KEY")
    if not api_key:
        pytest.skip("PPQ_API_KEY not set — skipping grounding measurement")

    from app.core.config import Settings
    from app.schemas.context import BuildContextRequest
    from app.schemas.generation import GenerateAnswerRequest
    from app.schemas.search import SearchRequest
    from app.services.answer_verifier_grounding import GroundingAnswerVerifier
    from app.services.answer_verifier_nli import NliAnswerVerifier
    from app.services.context_builder import DefaultContextBuilder
    from app.services.llm_backend import PpqLlmBackend
    from app.services.retrieval.base import RetrievalHit

    settings = Settings()
    llm = PpqLlmBackend(
        base_url="https://api.ppq.ai/v1",
        api_key=api_key,
        model_name=settings.llm_model_name,
        default_temperature=settings.llm_temperature,
        default_max_output_tokens=settings.llm_max_output_tokens,
    )
    context_builder = DefaultContextBuilder()
    nli = NliAnswerVerifier(
        scoring_mode="not_contradicted",
        unsupported_ratio=settings.nli_unsupported_ratio,
    )
    grounding = GroundingAnswerVerifier(
        threshold=GROUNDING_THRESHOLD,
        unsupported_ratio=GROUNDING_RATIO_PRODUCTION,
    )

    dataset = load_dataset(HELDOUT_PATH)
    questions = [q for q in dataset.questions if q.evidence]
    assert len(questions) >= 60

    per_question: list[dict] = []
    grounding_sentence_times: list[float] = []

    for question in questions:
        search_response = eval_stack.search_service.search(
            context=eval_stack.context,
            payload=SearchRequest(query=question.query, top_k=5),
        )
        context_payload = context_builder.build(
            BuildContextRequest(
                hits=[
                    RetrievalHit(
                        document_id=item.document_id,
                        chunk_id=item.chunk_id,
                        score=item.score,
                        text=item.text,
                        page_start=item.page_start,
                        page_end=item.page_end,
                        heading_path=item.heading_path,
                        route=item.route,
                    )
                    for item in search_response.items
                ],
                document_titles={
                    item.document_id: item.document_title for item in search_response.items
                },
                max_characters=4000,
                max_blocks=None,
            )
        )
        if context_payload.block_count == 0:
            per_question.append({
                "question_id": question.id,
                "language": question.language,
                "status": "no_context",
            })
            continue

        generation = llm.generate(
            GenerateAnswerRequest(question=question.query, context_payload=context_payload)
        )
        answer_text = generation.answer_text

        nli_summary = nli.verify(answer_text=answer_text, context_payload=context_payload)

        start = time.perf_counter()
        grounding_summary = grounding.verify(
            answer_text=answer_text, context_payload=context_payload
        )
        elapsed = time.perf_counter() - start
        if grounding_summary.sentence_count:
            grounding_sentence_times.append(elapsed / grounding_summary.sentence_count)

        unsupported_ratio_actual = (
            grounding_summary.unsupported_sentence_count / grounding_summary.sentence_count
            if grounding_summary.sentence_count
            else 1.0
        )
        per_question.append({
            "question_id": question.id,
            "language": question.language,
            "status": "answered",
            "answer_text": answer_text,
            "context_blocks": [b.text for b in context_payload.blocks],
            "context_citation_ids": [b.citation_id for b in context_payload.blocks],
            "nli_not_contradicted": {
                "status": nli_summary.status,
                "faithfulness": round(_faithfulness(nli_summary), 4),
                "sentence_count": nli_summary.sentence_count,
            },
            "grounding": {
                "status": grounding_summary.status,
                "status_at_ratio_0_2": (
                    "supported" if unsupported_ratio_actual <= GROUNDING_RATIO_SENSITIVITY
                    else "unsupported"
                ),
                "faithfulness": round(_faithfulness(grounding_summary), 4),
                "sentence_count": grounding_summary.sentence_count,
                "unsupported_sentences": [
                    s.sentence for s in grounding_summary.sentences if s.status == "unsupported"
                ],
            },
        })

    answered = [q for q in per_question if q["status"] == "answered"]
    assert len(answered) >= 55, f"Only {len(answered)} questions produced answers"

    def _mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    nli_faith = _mean([q["nli_not_contradicted"]["faithfulness"] for q in answered])
    grounding_faith = _mean([q["grounding"]["faithfulness"] for q in answered])
    mean_sentence_ms = round(1000 * _mean(grounding_sentence_times), 1)

    aggregates = {
        "answered": len(answered),
        "nli_not_contradicted": {
            "faithfulness": nli_faith,
            "accept_rate": _mean([
                1.0 if q["nli_not_contradicted"]["status"] == "supported" else 0.0
                for q in answered
            ]),
        },
        "grounding": {
            "faithfulness": grounding_faith,
            "accept_rate_ratio_0_0": _mean([
                1.0 if q["grounding"]["status"] == "supported" else 0.0 for q in answered
            ]),
            "accept_rate_ratio_0_2": _mean([
                1.0 if q["grounding"]["status_at_ratio_0_2"] == "supported" else 0.0
                for q in answered
            ]),
            "mean_per_sentence_verify_ms": mean_sentence_ms,
        },
        "adr_0019_criteria": {
            "c1_grounding_faithfulness_ge_0_85": grounding_faith >= 0.85,
            "c3_mean_sentence_verify_le_500ms": mean_sentence_ms <= 500.0,
            "c2_canary_catch_rate": "see hallucination_canaries.json",
        },
    }

    report = {
        "report": "grounding_vs_nli",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "llm": {"backend": "ppq", "model": settings.llm_model_name},
        "verifiers": {
            "nli": {"mode": "not_contradicted", "unsupported_ratio": settings.nli_unsupported_ratio},
            "grounding": {
                "model": "lytang/MiniCheck-Flan-T5-Large",
                "threshold": GROUNDING_THRESHOLD,
                "unsupported_ratio": GROUNDING_RATIO_PRODUCTION,
            },
        },
        "aggregates": aggregates,
        "per_question": per_question,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nGrounding comparison written: {REPORT_PATH}")
    print(json.dumps(aggregates, indent=2))
