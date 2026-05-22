# ADR-0015: Eval Harness Implementation

Status: Accepted
Date: 2026-05-23

## Context

Phase 4 exit criteria require measured faithfulness ≥ 0.85 and negative-answer compliance ≥ 0.90 on the held-out eval set (`docs/uber-rag/eval/heldout-v1.yaml`). The eval harness design exists (`docs/uber-rag/EVALUATION_HARNESS.md`) and the 170-question heldout set is drafted, but no runner, scorer, or reporter has been implemented. The current answer verifier uses casefolded substring overlap, which will produce low faithfulness scores because LLM outputs paraphrase rather than copy verbatim.

## Decision

### 1. Harness invokes ChatService in-process

The harness calls `ChatService.answer()` directly (Python function call), not over HTTP. This keeps the harness fast enough for iterative development and avoids needing a running server. An HTTP smoke test is added separately under `apps/api/app/tests/integration/` for contract verification.

### 2. Faithfulness metric: NLI-verified sentence support rate

Faithfulness = fraction of sentences in answered outputs that the NLI verifier marks as "supported" by the context, averaged across questions. The NLI verifier uses `cross-encoder/nli-deberta-v3-base` to score each answer sentence against each context block as a (premise, hypothesis) pair. A sentence is "supported" if the max entailment score across blocks exceeds the configured threshold (default 0.5).

Threshold from ROADMAP: ≥ 0.85.

### 3. Negative-answer compliance: status match rate

Negative-answer compliance = fraction of `type: negative` questions where `ChatResponse.status == "not_enough_evidence"`. These questions expect no indexed content, so the system should always return not_enough_evidence.

Threshold: ≥ 0.90.

### 4. answer_contains / answer_absent: informational, not gating

Deterministic casefolded substring assertions per question. Report pass rate alongside faithfulness. Do not gate Phase 4 on these — they are a Phase 5 polish target.

### 5. NLI verifier replaces substring verifier for production

The substring verifier (`AnswerVerifier`) is retained as a fallback for tests. A new `NliAnswerVerifier` using `cross-encoder/nli-deberta-v3-base` becomes the production default. Selection is wired through `Settings.verifier_backend`.

### 6. Real token streaming replaces fake SSE

The current `/chat/stream` emits a single `start → answer → done` sequence. This is replaced with real token-level streaming where the LLM generates tokens incrementally via SSE, and the client receives tokens as they arrive.

## Consequences

- **Positive:** Phase 4 exit criteria become measurable with real numbers. NLI verifier handles paraphrase correctly. Real streaming enables responsive UI.
- **Negative:** NLI model adds ~1-2 min load time on CPU. Harness requires BGE-M3 model for embedding fixtures (~3 min CPU). These are session-scoped to amortize cost.
- **Risk:** If NLI faithfulness cannot reach 0.85 after 3 tuning cycles, ADR-0016 will revise the threshold with evidence.

## Alternatives considered

- **HTTP-based harness:** Slower, requires running server, harder to iterate. Rejected for speed.
- **LLM-as-judge for faithfulness:** Non-deterministic, expensive, slow. NLI cross-encoder is deterministic and fast after model load.
- **Keeping substring verifier as production default:** Would produce unacceptably low faithfulness scores on paraphrased answers. NLI is the correct semantic check.
- **Full 170-question corpus for Phase 4:** Too much ground-truth annotation work. 15-question subset is sufficient to measure the verifier improvement.

## References

- `docs/uber-rag/EVALUATION_HARNESS.md` — harness design
- `docs/uber-rag/EVALUATION_PLAN.md` — thresholds and scoring policy
- `docs/uber-rag/eval/heldout-v1.yaml` — 170-question eval set
- `docs/uber-rag/ROADMAP.md` lines 190-195 — Phase 4 exit criteria
- `apps/api/app/services/answer_verifier.py` — current substring verifier
- `apps/api/app/services/chat_service.py` — orchestrator to evaluate
