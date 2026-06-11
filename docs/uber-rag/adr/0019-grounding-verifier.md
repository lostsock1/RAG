# ADR-0019: Grounding Verifier — MiniCheck-Flan-T5-Large

Status: Proposed (criteria frozen; promotion pending D3 measurement)
Date: 2026-06-11

## Context

ADR-0016 selected `not_contradicted` NLI scoring as the production faithfulness
metric after strict entailment proved non-functional (0.113/0.133 — generic NLI
classifies LLM paraphrase as "neutral"). ADR-0016 honestly records the cost:
`not_contradicted` is a **contradiction guardrail, not a support metric**. A
hallucination on a topic absent from the corpus passes, because no context block
contradicts it. ADR-0016's revisit trigger #1 anticipates exactly this ADR: a
model that distinguishes grounded paraphrase from ungrounded content.

The Phase D entry gate (`research/2026-06-11-phase-d-entry.md`) verified current
candidates against primary sources. MiniCheck models are trained specifically
for grounding verification — "is this claim supported by this document" — on
synthetic data built to include paraphrase, which is precisely the failure mode
that broke entailment mode.

## Decision

**Add a `grounding` verifier backend defaulting to `lytang/MiniCheck-Flan-T5-Large`,
and promote it to the production default if and only if the frozen criteria
below are met in the D3 measurement.**

### Selection rationale

| Constraint | MiniCheck-Flan-T5-Large |
|---|---|
| Commercially usable license | MIT (verified on card 2026-06-11) |
| No `trust_remote_code` | Plain `transformers` seq2seq (HHEM-2.x and Bespoke-7B fail this; ADR-0014 posture) |
| CPU-inference viable | 783M — same class as the BGE reranker; runs under the ADR-0018 verification gate |
| Sentence × evidence scoring | Native: sentence-level `(document, claim) → P(support)`; the authors recommend caller-side sentence splitting — our verifier seam already does this |
| Grounding (not generic NLI) evidence | LLM-AggreFact best-under-1B per card; "on par with GPT-4" claim |

Rejected: `Bespoke-MiniCheck-7B` (no license on card, custom_code, 7B);
HHEM-2.x (`trust_remote_code`, despite Apache-2.0 — revisit if a standard
architecture ships); granite-guardian 3.x (Apache-2.0 but 2–3B generation-style
judging — GPU-era reopen candidate); `MiniCheck-RoBERTa-Large` (kept as a
faster-CPU fallback config, slightly weaker per paper).

### Implementation shape (D2)

- New `GroundingAnswerVerifier` (`apps/api/app/services/answer_verifier_grounding.py`)
  mirroring `NliAnswerVerifier`: same sentence splitter, per sentence × per
  block scoring, max-over-blocks support probability, `threshold` +
  `unsupported_ratio` aggregation, lazy model load, citation IDs from the
  best-supporting block.
- Inference per the official recipe (extracted in the entry note):
  `"predict: " + block_text + eos + sentence`, forward with zero decoder token,
  `P(support) = softmax(logits[:, [3, 209]])[1]`.
- Config: `verifier_backend` gains `"grounding"`; `grounding_model_name`
  (default `lytang/MiniCheck-Flan-T5-Large`), `grounding_threshold` (default
  0.5), `grounding_unsupported_ratio` (default **0.0** — a true support metric
  should be all-sentences-supported by default; 0.2 sensitivity is reported in
  D3 but is not the production config).
- Process-cached instance in the chat route (the ADR-0018 per-request reload
  fix applies identically) and verification runs under the ADR-0018
  process-wide gate (any CPU model thrashes the same way without it).
- Tests: deterministic fake-model unit tests in the default suite; real-model
  paraphrase/contradiction/fabrication tests live in `tests/eval/` (nightly CI
  + on-demand), keeping the backend suite fast — FT5-Large weights are ~3 GB.

## Frozen promotion criteria (set BEFORE measurement — D3 applies them mechanically)

Promote `grounding` to production default iff ALL of:

1. **Faithfulness ≥ 0.85** on the 60-question evidence-backed subset at the
   production config (threshold 0.5, unsupported_ratio 0.0), where answers are
   generated ONCE by the production LLM (ppq Llama 3.3 70B) and the identical
   answers are scored by both verifiers.
2. **Canary catch-rate ≥ 80%** (D4): of fabricated-but-plausible answer
   sentences that `not_contradicted` passes, the grounding verifier rejects at
   least 80%.
3. **Latency compatible with streaming**: mean per-sentence verify time on CPU
   under the verification gate ≤ 500 ms (D3 records it); the ADR-0017 SLA must
   remain satisfiable per the ADR-0018 latency model.

On promotion: `Settings.verifier_backend` default flips to `"grounding"`,
ADR-0016 is marked superseded-in-part (its `not_contradicted` mode remains the
configured fallback), and this ADR moves to Accepted (measured). If any
criterion fails: this ADR moves to Rejected-with-data, `not_contradicted`
stays, and the measurement is committed anyway — either outcome is a success of
the rig.

## Consequences

### Positive
- Faithfulness becomes a true support metric: ungrounded fabrications on
  absent topics are caught (the documented ADR-0016 blind spot).
- Same seam, same gate, no new dependency, no trust_remote_code.
- ADR-0018 streaming semantics strengthen automatically: per-sentence gating
  now gates on actual grounding.

### Negative
- Second ~3 GB model in the serving footprint (NLI fallback remains available;
  air-gap bundle grows).
- Per-sentence latency expected somewhat higher than deberta-base NLI
  (783M seq2seq vs 184M cross-encoder) — criterion 3 guards this.
- English-centric training: DE/PT grounding quality is unmeasured until the
  multilingual generation slice (E5/D-followup); the NLI fallback shares this
  caveat.

## References

- `docs/uber-rag/research/2026-06-11-phase-d-entry.md` — entry gate + recipe
- `docs/uber-rag/adr/0016-faithfulness-metric-selection.md` — superseded-in-part on promotion
- `docs/uber-rag/adr/0018-incremental-verified-streaming.md` — gate + latency model
- arXiv:2404.10774 — MiniCheck (EMNLP 2024)

## Revisit triggers

- HHEM ships a standard-architecture (no trust_remote_code) release → re-bench.
- GPU hardware arrives → granite-guardian / Bespoke-class models re-enter.
- DE/PT grounding measured weak → multilingual grounding verifier search.
- MiniCheck-RoBERTa-Large needed if criterion 3 (latency) fails marginally.
