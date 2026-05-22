"""Step 9: Streaming load test — concurrent chat requests with latency measurement."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import anyio
import pytest

from tests.eval.conftest import EvalStack

# 6 questions that should return results from the fixture corpus
LOAD_TEST_QUESTIONS = [
    "What is the second law of thermodynamics?",
    "What is Le Chatelier's principle?",
    "What are the main organelles in a eukaryotic cell?",
    "What is the difference between supply and demand?",
    "What are the stages of grief according to Kübler-Ross?",
    "What is the Mohs hardness scale?",
]


@dataclass
class StreamLatency:
    question: str
    first_token_ms: float | None  # None if no tokens (not_enough_evidence)
    total_ms: float
    event_count: int
    status: str  # "answered" or "not_enough_evidence"
    error: str | None = None


async def _run_stream_request(
    chat_service, context, question: str, request_id: int
) -> StreamLatency:
    """Run a single streaming request and measure latencies."""
    from app.schemas.chat import ChatRequest

    start = time.perf_counter()
    first_token_time = None
    event_count = 0
    final_status = "unknown"

    try:
        async for event in chat_service.answer_stream(
            context=context,
            payload=ChatRequest(question=question),
        ):
            event_count += 1
            if event["type"] == "token" and first_token_time is None:
                first_token_time = time.perf_counter()
            if event["type"] == "final":
                final_status = event["data"]["status"]

        total_ms = (time.perf_counter() - start) * 1000.0
        first_token_ms = (first_token_time - start) * 1000.0 if first_token_time else None

        return StreamLatency(
            question=question,
            first_token_ms=first_token_ms,
            total_ms=total_ms,
            event_count=event_count,
            status=final_status,
        )
    except Exception as exc:
        total_ms = (time.perf_counter() - start) * 1000.0
        return StreamLatency(
            question=question,
            first_token_ms=None,
            total_ms=total_ms,
            event_count=event_count,
            status="error",
            error=str(exc),
        )


def _percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile of a sorted list."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * p / 100.0)
    return sorted_vals[min(idx, len(sorted_vals) - 1)]


@pytest.mark.slow
@pytest.mark.runload
@pytest.mark.anyio
async def test_streaming_load_concurrent(eval_stack: EvalStack, monkeypatch):
    """Fire 5 concurrent streaming requests and measure first-token latency."""
    api_key = os.environ.get("PPQ_API_KEY")
    if not api_key:
        pytest.skip("PPQ_API_KEY not set — skipping streaming load test")

    # Swap in real LLM + NLI verifier from shared Settings
    from app.core.config import Settings
    from app.services.llm_backend import PpqLlmBackend
    from app.services.answer_verifier_nli import NliAnswerVerifier

    settings = Settings()

    real_llm = PpqLlmBackend(
        base_url="https://api.ppq.ai/v1",
        api_key=api_key,
        model_name=settings.llm_model_name,
        default_temperature=settings.llm_temperature,
        default_max_output_tokens=settings.llm_max_output_tokens,
    )
    eval_stack.chat_service._llm_backend = real_llm
    eval_stack.chat_service._answer_verifier = NliAnswerVerifier(
        entailment_threshold=settings.nli_entailment_threshold,
        scoring_mode=settings.nli_scoring_mode,
        unsupported_ratio=settings.nli_unsupported_ratio,
    )

    # Disable audit writes
    monkeypatch.setattr(
        "app.services.chat_service.write_audit_event",
        lambda *a, **kw: None,
    )

    # Warmup: single request to pre-load NLI model and warm the LLM connection.
    # The NLI cross-encoder model loads lazily on first verify() call (~30s).
    # Without warmup, the first concurrent request pays this cost, inflating
    # its total latency and potentially its first-token latency if the event
    # loop blocks during model load.
    print("\n  Warmup request (pre-loading NLI model)...")
    warmup_result = await _run_stream_request(
        eval_stack.chat_service,
        eval_stack.context,
        LOAD_TEST_QUESTIONS[0],
        request_id=-1,
    )
    print(
        f"  Warmup done: status={warmup_result.status} "
        f"total={warmup_result.total_ms:.0f}ms "
        f"first_token={warmup_result.first_token_ms:.0f}ms" if warmup_result.first_token_ms else
        f"  Warmup done: status={warmup_result.status} total={warmup_result.total_ms:.0f}ms"
    )

    # Build 5 concurrent requests (cycling through the 6 questions)
    num_concurrent = 5
    results: list[StreamLatency] = []

    async with anyio.create_task_group() as tg:
        for i in range(num_concurrent):
            question = LOAD_TEST_QUESTIONS[i % len(LOAD_TEST_QUESTIONS)]

            async def _task(q: str = question, rid: int = i) -> None:
                r = await _run_stream_request(
                    eval_stack.chat_service,
                    eval_stack.context,
                    q,
                    request_id=rid,
                )
                results.append(r)

            tg.start_soon(_task)

    # Report
    print(f"\n{'=' * 70}")
    print(f"STREAMING LOAD TEST REPORT")
    print(f"{'=' * 70}")
    print(f"Concurrent requests: {num_concurrent}")
    print()

    for i, r in enumerate(results):
        ft = f"{r.first_token_ms:.0f}ms" if r.first_token_ms else "N/A"
        err = f" ERROR: {r.error}" if r.error else ""
        print(f"  Request {i}: status={r.status} first_token={ft} total={r.total_ms:.0f}ms events={r.event_count}{err}")

    # Compute percentiles for first-token latency
    first_token_values = [r.first_token_ms for r in results if r.first_token_ms is not None]
    total_values = [r.total_ms for r in results]

    if first_token_values:
        p50_ft = _percentile(first_token_values, 50)
        p95_ft = _percentile(first_token_values, 95)
        print(f"\nFirst-token latency: P50={p50_ft:.0f}ms P95={p95_ft:.0f}ms")
    else:
        p50_ft = p95_ft = 0.0
        print("\nNo first-token latencies to measure (all not_enough_evidence?)")

    if total_values:
        p50_total = _percentile(total_values, 50)
        p95_total = _percentile(total_values, 95)
        print(f"Total latency:       P50={p50_total:.0f}ms P95={p95_total:.0f}ms")

    print(f"{'=' * 70}")

    # Assertions
    errors = [r for r in results if r.error is not None]
    assert len(errors) == 0, f"{len(errors)} requests failed with errors"

    # At least some requests should return "answered"
    answered = [r for r in results if r.status == "answered"]
    assert len(answered) >= 3, f"Expected >= 3 answered, got {len(answered)}"

    # Latency assertions per ADR-0017: P50 < 5s, P95 < 6s under 5 concurrent
    # Measured baseline: P50 ~2.5s, P95 ~3.4s with ppq.ai + NLI verifier.
    # These ceilings are regression guards, not targets. The ADR-0008 ~2s
    # target gap is acknowledged in ADR-0017.
    if first_token_values:
        assert p50_ft < 5000, f"P50 first-token latency {p50_ft:.0f}ms exceeds 5000ms (ADR-0017)"
        assert p95_ft < 6000, f"P95 first-token latency {p95_ft:.0f}ms exceeds 6000ms (ADR-0017)"
