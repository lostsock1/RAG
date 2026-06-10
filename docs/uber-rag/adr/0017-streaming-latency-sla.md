# ADR-0017: Streaming First-Token SLA Under Load

Status: Accepted — **SLA currently FAILING by design** after the evidence-safe
streaming change (see "Re-measurement 2026-06-10"); remediation is ADR-0018
sentence-incremental verified streaming (master plan Phase B), not an SLA revision.
Date: 2026-05-23 (re-measured 2026-06-10)

## Context

ADR-0008 establishes a "~2 second target" for user-visible `/chat` latency on Tier 1 (exact) and Tier 2 (semantic normal) queries. The Phase 4 load test measures first-token latency under 5 concurrent streaming requests with the real PpqLlmBackend + NLI verifier.

Measured results (commit `7d98148`, reconfirmed with Settings-wired verifier):

| Metric | Typical | Outlier observed | ADR-0008 target |
|---|---|---|---|
| P50 first-token | ~2.5s | — | ~2s |
| P95 first-token | ~3.5s | ~8.8s (ppq.ai queue delay) | — |
| Error rate | 0% | — | — |

The measured P50 exceeds ADR-0008's ~2s target. The primary cause is ppq.ai API latency: the LLM provider adds variable inference time that we cannot control until we add a local or fallback provider. The NLI verifier runs after answer generation (in the streaming path, it runs post-generation), so it does not affect first-token latency. *(Superseded by the 2026-06-10 re-measurement below: verification is now deliberately in the first-token path.)*

## Re-measurement 2026-06-10 — after evidence-safe token buffering

The 2026-05-23 streaming hardening (commit `1ce0d30`) buffers **all** generated
tokens until post-generation verification passes, so no unsupported text is ever
emitted. Consequence: "first token" now means "first **verified** token," and the
revisit trigger *"the NLI verifier is moved into the first-token path"* has fired —
deliberately, for evidence discipline, not as an accidental regression.

Canonical re-measurement (`tests/eval/reports/load_post_buffering.json`, single
pinned-asyncio run, 5 concurrent, real ppq + NLI not_contradicted):

| Metric | 2026-05-23 (pre-buffering) | 2026-06-10 (post-buffering) | SLA | Verdict |
|---|---|---|---|---|
| P50 first-token | ~2.5s | **5.97s** | < 5s | **FAIL** |
| P95 first-token | ~3.5s | **10.75s** | < 10s | **FAIL** |
| Answered / errors | 5/5, 0 | 5/5, 0 | 0 errors | pass |

Two additional samples from the same day (7.0s/14.6s and 4.7s/8.6s) show ppq.ai
variance straddles the ceilings; the structural fact is that `first_token ≈ total`
in every request — tokens arrive only after full generation plus verification.

Resolution: **the SLA stands and the failure is accepted as known-and-tracked.**
Reverting evidence safety to win back latency is not an option (architecture
invariant #5). ADR-0018 (sentence-incremental verified streaming, master plan
Phase B) restores first-verified-token latency to ~LLM-bound levels while keeping
the invariant. The load test keeps its assertions and stays red until Phase B
lands; it is excluded from CI (requires `PPQ_API_KEY`).

Methodology note: the load test is now pinned to a single anyio backend
(asyncio) — the anyio plugin otherwise runs it twice (asyncio + trio), doubling
real-LLM cost and overwriting the report; the earlier "~2.5s" numbers were
measured under the same per-run conditions, so the comparison holds.

P95 is highly sensitive to ppq.ai API variability under concurrent load. With only 5 concurrent requests, P95 is essentially the maximum. A single slow ppq.ai request (e.g., queue delay) can inflate P95 from ~3.5s to ~9s. This is provider variability, not a system regression.

## Decision

Adopt the following SLA for streaming first-token latency under 5 concurrent requests:

- **P50 first-token < 5s**
- **P95 first-token < 10s**
- **0 errors**

Justification:

1. **ppq.ai is the binding constraint.** With an API-based LLM provider, first-token latency is dominated by the provider's inference queue. Measured P50 ~2.5s is within normal range for a 70B model served through an aggregator API under concurrent load.

2. **5s P50 is a ceiling, not a target.** The measured P50 (~2.5s) is well within this ceiling. The ceiling exists to catch regressions (e.g., NLI model loading in the hot path, broken connection pooling), not to define acceptable performance.

3. **ADR-0008 gap is acknowledged.** This SLA does NOT meet ADR-0008's ~2s target. The gap is caused by the API-based LLM provider and will close when:
   - A local vLLM or llama.cpp provider is available (ADR-0004 deferred path)
   - A faster fallback provider is wired (e.g., Groq, Together)
   - Speculative decoding or prompt caching reduces provider latency

4. **P95 ceiling accounts for ppq.ai API variability.** With 5 concurrent requests, P95 is the maximum. A single slow ppq.ai request (queue delay, cold start) can inflate P95 to ~9s. The 10s ceiling catches genuine regressions (e.g., NLI model loading in the hot path) while tolerating provider variability.

## Consequences

### Positive

- The load test now enforces a meaningful SLA instead of a 15s P95 ceiling that would pass almost any regression.
- The SLA is achievable with the current ppq.ai provider (measured P50 ~2.5s, P95 ~3.4s).
- The gap to ADR-0008 is explicitly documented, not hidden.

### Negative

- This SLA does not meet ADR-0008's ~2s target. Users may experience noticeable latency on concurrent requests.
- The 5s P50 ceiling is generous — a regression from 2.5s to 4.5s would still pass. The test is a regression guard, not a precision instrument.
- Until a local or fallback provider is available, there is no path to closing the ADR-0008 gap within the current architecture.

## Alternatives considered

- **Tighten to P50 < 3s / P95 < 5s** — rejected. P95 is too sensitive to ppq.ai API variability. A single slow request can push P95 above 5s even when the system is functioning correctly.
- **Tighten to P50 < 1.5s / P95 < 3.0s** (original Phase 4 bar) — rejected. Not achievable with ppq.ai under concurrent load. Would require a local LLM provider.
- **Keep 5s/15s ceilings** — rejected. The 15s P95 ceiling is meaningless; it would pass even with a severe regression.

## References

- `docs/uber-rag/adr/0008-fast-hot-path-async-quality.md` — ~2s target, two-path architecture
- `docs/uber-rag/adr/0004-llm-adapter-and-provider.md` — ppq.ai default, vLLM/llama.cpp deferred
- `tests/eval/load/test_chat_load.py` — load test with SLA assertions
- `apps/api/app/core/config.py` — Settings with NLI verifier configuration

## Revisit triggers

Reopen this ADR if any of the following happens:

- A local vLLM or llama.cpp provider is wired and measured P50 drops below 2s
- A faster API fallback provider (Groq, Together) is added and measured P50 drops below 2s
- ppq.ai latency degrades significantly (P50 > 5s under 5 concurrent)
- The NLI verifier is accidentally moved into the first-token path (regression)
- Product requirements change to require sub-2s first-token under load
