# ADR-0019: Grounding Verifier — MiniCheck-Flan-T5-Large

Status: **Rejected (with data), 2026-06-11** — frozen criteria applied
mechanically: criterion 2 passed (canary catch rate 1.00), criteria 1 and 3
failed (faithfulness 0.578 vs ≥ 0.85; per-sentence latency 3964 ms vs
≤ 500 ms). `not_contradicted` (ADR-0016) remains the production default. The
`grounding` backend stays merged and config-selectable, and the canary suite
runs nightly in CI as the standing blind-spot guard. See "Measurement results"
below — the failure analysis surfaced two real generation-quality findings.
Date: 2026-06-11

**Re-measurement 2026-06-11 (post-E0a, primary reopen path executed):** after
the answer-style fix (`1f41e40` — human source labels, anti-meta-discourse
rule), criterion 1 was re-run on freshly generated answers per the revisit
trigger: **criterion 1 now PASSES — grounding faithfulness 0.9007** (was
0.578), accept rate at production ratio 0.0 = 0.85 (was 0.3667); 60/60
answered; NLI reference faithfulness 1.0. The meta-discourse rejection class
is gone; the 9 remaining rejected answers decompose into derived-inference
strictness (e.g. an explicit °C→K addition), residual source-narration
sentences, and comparative synthesis across blocks — no substantive
fabrication observed. Criterion 3 still FAILS (4553 ms/sentence CPU, measured
with light concurrent load; same ~9× over budget as D3's 3964 ms).
**Rejection stands on criterion 3 alone.** The optional c3 path from the
Phase-D bindings is now justified: measure `MiniCheck-RoBERTa-Large`
(0.4B classifier; same family, kept as faster-CPU fallback in the selection
table) offline against all three criteria — c1 by re-scoring the persisted
answers, c2 on the canary suite, c3 latency — no LLM calls required. Report:
`tests/eval/reports/grounding_vs_nli.json` (before-run preserved at git
`HEAD~1`).

**c3 path executed 2026-06-11 — REJECTION CONFIRMED, now on dual grounds.**
`MiniCheck-RoBERTa-Large` (MIT, `RobertaForSequenceClassification`, entry
gate re-verified via HF API; official recipe verified upstream: single-string
`chunk</s>claim`, 512-token window, doc chunked to `max_len − 300` tokens,
max-aggregated, `P = softmax(logits)[:, 1]`) measured offline on the
identical persisted answers (`tests/eval/reports/grounding_roberta_offline.json`):
**c1 0.7632 FAIL** (vs FT5-L 0.9007 — "slightly weaker per paper" confirmed
on our distribution), **c2 1.00 PASS** (10/10 blind-spot fabrications caught;
paraphrase + contradiction controls clean), **c3 1918 ms/sentence FAIL**
(2.4× faster than FT5-L's 4553 ms, still ~3.8× over the bar). No MiniCheck
variant passes all three criteria on this CPU: FT5-L fails c3 only; RoBERTa-L
fails c1 and c3. The classification recipe path is merged and
config-selectable (`grounding_model_name`), so any future GPU/ONNX reopen
can A/B both variants without code changes. Remaining c3 levers (ONNX int8,
top-k-block prefiltering, GPU hardware) stay listed under Revisit triggers.

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

## Measurement results (D3 + D4, 2026-06-11)

| Criterion | Frozen bar | Measured | Verdict |
|---|---|---|---|
| 1. Grounding faithfulness (60 q, identical LLM answers) | ≥ 0.85 | **0.578** | FAIL |
| 2. Canary catch rate on the `not_contradicted` blind spot | ≥ 0.80 | **1.00** (10/10; controls clean) | PASS |
| 3. Mean per-sentence verify latency (CPU, this hardware) | ≤ 500 ms | **3964 ms** | FAIL |

Reference: `not_contradicted` on the same answers: faithfulness 0.9985, accept
rate 1.00. Reports: `tests/eval/reports/grounding_vs_nli.json`,
`tests/eval/reports/hallucination_canaries.json`.

### Failure taxonomy (criterion 1)

The 0.578 is **not** primarily verifier blindness — it decomposes into:

1. **Meta-discourse in answers (54 of 81 rejected sentences).** The production
   LLM wraps facts in citation meta-language — *"According to the biology
   textbook (rank=1), homeostasis is …"*, *"(Evidence block rank=4)"*, *"This
   is stated in the text of rank=1."* MiniCheck (correctly, strictly) cannot
   ground the wrapper against block text; pure meta-sentences contain no
   groundable claim at all. The NLI guardrail passes all of it silently.
2. **Splitter fragmentation of numbered lists** — fragments like
   `"f(a) is defined\n2."` are not checkable claims (e.g., h18).
3. Residual strictness on heavily-reworded composites.

**Product findings surfaced by this measurement (the real value of the run):**
- `rank=N` is leaked internal jargon: `llm_backend.py:204` renders
  `rank={block.rank}` into prompt block headers and the LLM parrots it into
  user-visible answers. Fix candidate (small, logged in the master plan):
  human-oriented source labels + a system-instruction rule against echoing
  them. The h16 "CODATA 2018" suspicion was checked and cleared — the fixture
  genuinely contains that text; no parametric fabrication observed in this run.
- Re-measurement of criterion 1 is only meaningful **after** the answer-style
  fix; the current number measures the style mismatch as much as the verifier.

### Criterion 3 note

783M seq2seq × (sentences × blocks) pairs at max-length 2048 is ~8× over the
streaming budget on this CPU. Paths if reopened: `MiniCheck-RoBERTa-Large`
(0.4B classifier head), ONNX int8, top-2-block prefiltering before grounding,
or GPU-era hardware.

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

- **The answer-style fix lands** (no meta-discourse / rank-leak in answers) →
  re-run D3; criterion 1 becomes meaningful. This is the primary reopen path.
- Criterion 3 path identified (RoBERTa variant measured fast enough, ONNX
  int8, block prefiltering, or GPU hardware) → re-run latency measurement.
- HHEM ships a standard-architecture (no trust_remote_code) release → re-bench.
- GPU hardware arrives → granite-guardian / Bespoke-class models re-enter.
- DE/PT grounding measured weak → multilingual grounding verifier search.
