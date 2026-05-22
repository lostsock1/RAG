# ADR-0016: Faithfulness Metric Selection

Status: Accepted
Date: 2026-05-23

## Context

The NLI answer verifier (`NliAnswerVerifier`) uses `cross-encoder/nli-deberta-v3-base` to score each answer sentence against each context block as a (premise, hypothesis) pair. The model outputs raw logits as a 3-element array: `[contradiction, entailment, neutral]`. After softmax, these yield three probabilities per sentence–block pair.

Two scoring modes are available:

1. **`entailment`** — uses `P(entailment)` as the support score. A sentence is "supported" only if some context block strictly entails it (score ≥ threshold). This is a **support metric**: it confirms that the answer is grounded in the evidence.

2. **`not_contradicted`** — uses `1 - P(contradiction)` as the support score. A sentence is "supported" if no context block contradicts it. This is a **guardrail metric**: it catches contradictions but passes both entailed and neutral sentences.

The `unsupported_ratio` parameter controls the overall verdict: if the fraction of unsupported sentences is at most this ratio, the overall status is "supported". Default 0.0 (all-or-nothing) for entailment mode; 0.2 was used with not_contradicted mode to tolerate up to 20% unsupported sentences.

Architecture invariant #5 (evidence discipline) states: *"answers must be source-bound. If evidence is missing, respond with a clear not-found. No improvisation."*

## Decision

**Default scoring mode: `entailment`** with `unsupported_ratio = 0.0`.

Rationale:

- `entailment` is a support metric — it confirms that each answer sentence is grounded in retrieved evidence. This directly enforces the evidence discipline invariant.
- `not_contradicted` is a guardrail metric — it only catches contradictions. A sentence that is topically unrelated to any context block but not explicitly contradicted would pass. This violates evidence discipline: the LLM could hallucinate content on a topic the corpus doesn't cover, and the verifier would not flag it.
- The product's trust model requires that answers are *supported by evidence*, not merely *not contradicted by evidence*. A "not contradicted" answer on a topic absent from the corpus is indistinguishable from a hallucination.
- `not_contradicted` remains available as a configuration option for environments where the LLM is trusted to stay on-topic and the primary concern is catching contradictions (e.g., internal tools with constrained prompts).

**Revised faithfulness threshold: TBD** (to be set after measuring both modes in Step 2).

The original Phase 4 threshold of ≥ 0.85 was set assuming `not_contradicted` mode. With `entailment` mode, the measured ceiling is expected to be lower because the cross-encoder classifies many valid paraphrases as "neutral" rather than "entailment." The threshold will be revised to a defensible value grounded in the measured ceiling.

## Data

Both modes measured on the 15-question answered subset of `heldout-v1.yaml`:

| Mode | scoring_mode | unsupported_ratio | Faithfulness |
|---|---|---|---|
| Entailment (strict) | `entailment` | 0.0 | TBD |
| Not contradicted (lenient) | `not_contradicted` | 0.2 | TBD |

*(Numbers to be filled after Step 2 measurement.)*

## Consequences

### Positive

- Production verifier behavior matches the evidence discipline invariant.
- The headline faithfulness number is honest: it measures actual support, not absence of contradiction.
- Eval and production share the same default configuration (via `Settings`), preventing the test/prod divergence that existed before this ADR.

### Negative

- Headline faithfulness will be lower than the previously reported 1.000 (which was measured under `not_contradicted` mode).
- The `cross-encoder/nli-deberta-v3-base` model classifies many valid paraphrases as "neutral" rather than "entailment." This means the entailment-mode faithfulness is a lower bound on true faithfulness — some supported sentences are misclassified as unsupported.
- The Phase 4 exit threshold of ≥ 0.85 will likely need revision downward.

### Failure modes by mode

| Failure mode | `entailment` catches it? | `not_contradicted` catches it? |
|---|---|---|
| Answer contradicts context | Yes | Yes |
| Answer hallucinates on topic absent from corpus | Yes (no entailment) | **No** (not contradicted) |
| Answer paraphrases context accurately | **Sometimes missed** (classified as neutral) | Yes |
| Answer elaborates beyond context | Yes (no entailment) | **No** (not contradicted) |

### Future improvement

A stronger faithfulness measurement requires either:
- A finer-grained NLI model that better distinguishes entailment from neutral for paraphrased content.
- LLM-as-judge verification as a complementary metric (non-deterministic, but better at recognizing paraphrase).
- These are Phase 5+ candidates, not Phase 4 blockers.

## Alternatives considered

- **`not_contradicted` as default** — rejected. Violates evidence discipline. A "not contradicted" metric is a guardrail, not a support metric. It would allow the system to claim high faithfulness while passing hallucinated content.
- **Dual reporting (both numbers as equals)** — rejected as the default. Both numbers should be reported, but the production default must be one mode. Reporting two equal-priority numbers creates ambiguity about what "faithfulness" means.
- **Lowering the entailment threshold below 0.5** — not considered in this ADR. Threshold tuning is a separate lever; the scoring mode decision is about what the metric measures, not how strict it is.

## References

- `apps/api/app/services/answer_verifier_nli.py` — NLI verifier implementation
- `docs/uber-rag/adr/0015-eval-harness-implementation.md` — eval harness design
- `docs/uber-rag/adr/0008-fast-hot-path-async-quality.md` — latency architecture (verifier is async in hot path)
- Architecture invariant #5: evidence discipline (`AGENTS.md`, `_shared.md`)
- Model card: https://huggingface.co/cross-encoder/nli-deberta-v3-base
