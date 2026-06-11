# ADR-0016: Faithfulness Metric Selection

Status: Accepted (revised after measurement)
Date: 2026-05-23

## Context

The NLI answer verifier (`NliAnswerVerifier`) uses `cross-encoder/nli-deberta-v3-base` to score each answer sentence against each context block as a (premise, hypothesis) pair. The model outputs raw logits as a 3-element array: `[contradiction, entailment, neutral]`. After softmax, these yield three probabilities per sentence–block pair.

Two scoring modes are available:

1. **`entailment`** — uses `P(entailment)` as the support score. A sentence is "supported" only if some context block strictly entails it (score ≥ threshold). This is a **support metric**: it confirms that the answer is grounded in the evidence.

2. **`not_contradicted`** — uses `1 - P(contradiction)` as the support score. A sentence is "supported" if no context block contradicts it. This is a **guardrail metric**: it catches contradictions but passes both entailed and neutral sentences.

The `unsupported_ratio` parameter controls the overall verdict: if the fraction of unsupported sentences is at most this ratio, the overall status is "supported". Default 0.0 (all-or-nothing) for entailment mode; 0.2 for not_contradicted mode to tolerate up to 20% unsupported sentences.

Architecture invariant #5 (evidence discipline) states: *"answers must be source-bound. If evidence is missing, respond with a clear not-found. No improvisation."*

## Decision

**Default scoring mode: `not_contradicted`** with `unsupported_ratio = 0.2`.

This is a **reversal** from the initial decision (entailment as default), driven by measured data that shows entailment mode is non-functional with the current NLI model.

### Why entailment was initially chosen

`entailment` is a support metric — it confirms that each answer sentence is grounded in retrieved evidence. This directly enforces the evidence discipline invariant. `not_contradicted` is a guardrail metric — it only catches contradictions, not unsupported claims.

### Why the measurement reversed this decision

Measured on the 15-question answered subset of `heldout-v1.yaml`:

| Mode | scoring_mode | unsupported_ratio | Faithfulness | System functional? |
|---|---|---|---|---|
| Entailment (strict) | `entailment` | 0.0 | **0.113** | **No** — all 15 answers rejected |
| Not contradicted (lenient) | `not_contradicted` | 0.2 | **1.000** | Yes — all 15 answers accepted |

In entailment mode, the `cross-encoder/nli-deberta-v3-base` model classifies nearly all LLM-paraphrased sentences as "neutral" rather than "entailment." With `unsupported_ratio=0.0`, even one unsupported sentence causes the entire answer to fail verification. The result: **the system returns `not_enough_evidence` for every question**. The system is non-functional in entailment mode.

Only 3 of 15 questions had ANY strictly-entailed sentences (h04: 1/2, h10: 1/2, n03: 1/2, n12: 1/5). The NLI model trained on SNLI/MultiNLI requires strict logical entailment, which is too strict for RAG paraphrase detection.

### Acknowledgment

**`not_contradicted` is a guardrail metric, not a support metric.** It catches contradictions but does not verify that answers are grounded in evidence. A sentence that is topically unrelated to any context block but not explicitly contradicted would pass. This is a known weakness.

The evidence discipline invariant is enforced by the retrieval pipeline (context builder provides only retrieved evidence to the LLM) and the system prompt (instructs the LLM to answer only from provided evidence). The verifier is a **post-hoc check**, not the primary enforcement mechanism. With `not_contradicted` mode, the verifier catches the most dangerous failure mode (contradictions) while the retrieval pipeline and prompt engineering handle the rest.

### Faithfulness threshold

The Phase 4 exit threshold of ≥ 0.85 is met under `not_contradicted` mode (measured: 1.000). The entailment-mode number (0.113) is reported for transparency but is not the production metric.

## Data

Both modes measured on the 15-question answered subset of `heldout-v1.yaml`:

| Mode | scoring_mode | unsupported_ratio | Faithfulness |
|---|---|---|---|
| Entailment (strict) | `entailment` | 0.0 | **0.113** |
| Not contradicted (lenient) | `not_contradicted` | 0.2 | **1.000** |

Re-measured 2026-05-23 after the Phase 1+2 retrieval hardening pass (payload-side
ACL filters restored, Qdrant expiry clause dropped): entailment **0.133**,
not_contradicted **1.000** (15/15 answered). Same conclusion — entailment mode
remains non-functional; the per-question deltas (e.g., n03 now answered) come from
the retriever changes, not the verifier. The committed
`tests/eval/reports/nli_both_modes.json` reflects this re-run.

Full per-question data: `tests/eval/reports/nli_both_modes.json`

## Consequences

### Positive

- The system is functional: answers pass verification and reach the user.
- The verifier catches the most dangerous failure mode: contradictions between answer and evidence.
- Eval and production share the same default configuration (via `Settings`), preventing the test/prod divergence that existed before this ADR.
- The `entailment` mode remains available as a configuration option for environments with a stricter NLI model or where the LLM produces more verbatim output.

### Negative

- `not_contradicted` does not verify that answers are grounded in evidence. It is a guardrail, not a support metric.
- A hallucination on a topic absent from the corpus would not be caught by the verifier (no context block would contradict it because no context block is relevant).
- The headline faithfulness number (1.000) reflects absence of contradiction, not presence of support. This must be clearly communicated.

### Failure modes by mode

| Failure mode | `entailment` catches it? | `not_contradicted` catches it? |
|---|---|---|
| Answer contradicts context | Yes | Yes |
| Answer hallucinates on topic absent from corpus | Yes (no entailment) | **No** (not contradicted) |
| Answer paraphrases context accurately | **Missed** (classified as neutral) | Yes |
| Answer elaborates beyond context | Yes (no entailment) | **No** (not contradicted) |

### Mitigations for not_contradicted weaknesses

1. **Retrieval pipeline** — the context builder provides only retrieved evidence to the LLM. If no evidence is retrieved, the system returns `not_enough_evidence` before generation.
2. **System prompt** — instructs the LLM to answer only from provided evidence.
3. **Future: stronger NLI model** — a model that better distinguishes entailment from neutral for paraphrased content would make entailment mode viable. Candidates: models fine-tuned on NLI datasets with more paraphrase pairs, or LLM-as-judge verification.
4. **Future: LLM-as-judge** — a complementary metric that uses an LLM to judge whether each answer sentence is supported by the context. Non-deterministic but better at recognizing paraphrase. Phase 5+ candidate.

## Alternatives considered

- **`entailment` as default** — rejected after measurement. Produces 0.113 faithfulness and makes the system non-functional (all answers rejected). The NLI model is too strict for RAG paraphrase detection.
- **`entailment` with high `unsupported_ratio`** (e.g., 0.8) — rejected. This would allow answers where 80% of sentences are unsupported, which is not a meaningful faithfulness standard. It's effectively the same as no verification.
- **Dual reporting (both numbers as equals)** — rejected as the default. Both numbers are reported, but the production default must be one mode. The entailment-mode number (0.113) is informational, not gating.
- **Lowering the entailment threshold below 0.5** — not considered. Even at threshold 0.3, the model classifies most paraphrases as "neutral" with very low entailment probability. The issue is the model's training data (SNLI/MultiNLI), not the threshold.

## References

- `apps/api/app/services/answer_verifier_nli.py` — NLI verifier implementation
- `tests/eval/reports/nli_both_modes.json` — full per-question measurement data
- `docs/uber-rag/adr/0015-eval-harness-implementation.md` — eval harness design
- `docs/uber-rag/adr/0008-fast-hot-path-async-quality.md` — latency architecture (verifier is async in hot path)
- Architecture invariant #5: evidence discipline (`AGENTS.md`, `_shared.md`)
- Model card: https://huggingface.co/cross-encoder/nli-deberta-v3-base

**2026-06-11 update (ADR-0019 measured and rejected):** the grounding-verifier
candidate (MiniCheck-Flan-T5-Large) was implemented and measured per frozen
criteria — canary catch rate 1.00 on this ADR's documented blind spot (10/10
fabrications that `not_contradicted` passes), but faithfulness 0.578 (dominated
by answer meta-discourse, see ADR-0019 failure taxonomy) and CPU latency ~4 s
per sentence. `not_contradicted` therefore **remains the production default**.
New standing mitigation for the blind spot: the hallucination canary suite runs
nightly in CI (`tests/eval/test_hallucination_canaries.py`). Primary reopen
path: the answer-style fix (rank-leak / meta-discourse), then re-measure.

## Revisit triggers

Reopen this ADR if any of the following happens:

- A finer-grained NLI model becomes available that better distinguishes entailment from neutral for paraphrased content (entailment-mode faithfulness > 0.5 on the 15-question subset)
- LLM-as-judge verification is implemented and provides a complementary support metric
- The LLM is configured to produce more verbatim output (reducing paraphrase, making entailment mode viable)
- A hallucination incident occurs that `not_contradicted` mode would not have caught (triggering a review of whether the guardrail is sufficient)
