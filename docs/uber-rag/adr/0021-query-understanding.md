# ADR-0021: Query Understanding — Route-Gated Multi-Query + Heuristic Decomposition

Status: **Proposed — decision rule frozen 2026-06-11, eval arm pending.**
Committed before measurement per house discipline (the rule must not be
shaped by the numbers it judges). The measurement table and the final
outcome will be appended below without altering the frozen rule.
Date: 2026-06-11

## Context

Ranking remains the measured weakness of the committed baseline (MRR@10
0.8337 / nDCG@10 0.8754 / recall@10 1.000 post-distractor,
`tests/eval/reports/retrieval_baseline.json`). The two in-freeze levers
measured so far both attack it from the *scoring* side and both lost on
their cost dimension or significance bar: the ADR-0014 reranker passes
quality (+0.0413 MRR@10) but fails query-time latency; ADR-0020 contextual
augmentation fails outright (breadcrumb sub-bar, llm harmful). Query
understanding attacks the *candidate generation* side instead: a single
query embedding can miss phrasings the corpus uses (vocabulary mismatch),
and multi-hop questions need evidence no single query surfaces.

Both arms ride the 2026-06-11 models freeze: multi-query reuses the frozen
answering LLM (ppq.ai Llama 3.3 70B) through the same OpenAI-compatible
provider settings; decomposition uses no model at all.

### Arms

- **multi_query**: ONE LLM call per gated search generates N=3 paraphrases
  of the user query (prompt asks for retrieval-oriented rewordings, one per
  line). The original query plus paraphrases each run the full
  lexical+dense+sparse retrieval; all rank lists merge through the existing
  RRF fusion (`fusion.py`, unchanged — RRF naturally sums evidence across
  query variants); the cross-encoder/stub rerank then runs against the
  ORIGINAL query (intent stays authoritative). Implementation note: the
  paraphrase call uses a small OpenAI-compatible client with an injectable
  transport (the `LlmBackend` protocol is answer-shaped —
  `GenerateAnswerRequest` requires a `ContextPayload` — so the paraphraser
  follows the ADR-0020 contextualizer precedent and shares the `llm_*`
  provider settings instead).
- **decompose**: heuristic, deterministic, LLM-free multi-hop detection —
  comparative/two-entity shapes ("compare X and Y", "difference between X
  and Y", "X vs Y", twin question clauses joined by "and") split into
  single-entity sub-queries that join the same fusion pool. Near-zero cost;
  fires only when a pattern matches (most questions pass through
  unexpanded).
- **both**: union of the two expansions, deduplicated, capped.

### Route gate (ADR-0008 discipline)

Expansion NEVER runs on exact/quoted routes — those bypass fusion entirely
today and keep doing so byte-identically. Only `semantic` routes (which
already pay for embedding + fusion + generation downstream) may pay the
extra cost. `query_understanding: Literal["disabled","multi_query",
"decompose","both"] = "disabled"`; when disabled the retriever code path is
byte-identical to today. A deterministic stub expander serves tests.

### Cost expectation (recorded up front)

The paraphrase call is a real ppq round-trip (~3 s measured for short
outputs in E2 calibration) on the search hot path of gated routes. The
frozen latency bar below (≤ 700 ms added P50, from the master plan) is
therefore expected to be the binding constraint for `multi_query` on the
current API-only serving — exactly the ADR-0014 situation. The honest
outcomes are the same ones recorded there: flip, or no-flip with the
quality result and the reopen path (local low-latency LLM serving)
documented. `decompose` has no such cost and is judged on quality alone.

## Decision rule (FROZEN before measurement)

Measured on the C3 rig (same session-scoped eval stack — query
understanding does NOT change ingestion, so arms reuse the committed
corpus/index), 60 evidence-backed heldout questions, production retrieval
shape (parent expansion ON, stub reranker), against the committed
post-distractor baseline aggregates.

**Flip the production `query_understanding` default to an arm iff ALL of:**

1. **Ranking lift:** overall MRR@10 lift ≥ **+0.02** OR overall nDCG@10
   lift ≥ **+0.02** vs the committed baseline (MRR@10 0.8337 / nDCG@10
   0.8754), and
2. **Recall guard:** overall recall@10 drop ≤ **0.02** (from 1.000), and
3. **Latency:** added search latency on gated routes (arm minus
   no-understanding control, same stack, same queries, warmed) ≤
   **700 ms at P50** — dev-Mac CPU is optimistic vs the VPS; any flip
   must be re-verified on the VPS before SLA-relevant defaults ship.

**Subset honesty clause (frozen):** needle/multilingual/multi-hop subset
lifts are *recorded for analysis* but are NOT deciding metrics — a
subset-only win does not flip the default (multiple-comparisons guard).
If a subset shows a strong isolated win, that is a recorded reopen path,
not a pass.

**Tie-breaker (frozen):** if more than one arm passes, the cheaper arm
wins (decompose ≺ multi_query ≺ both, by added latency and LLM cost)
unless a costlier arm exceeds the cheaper passing arm by ≥ **+0.02** on
mrr@10 or ndcg@10.

**Positive controls (mandatory, E1/E2 lesson — a silently inert arm must
not reproduce the baseline as "no win"):**

- multi_query: paraphrase call fired for every gated question
  (expanded_query_count == question count), paraphrases non-empty,
  distinct from the original after case-normalization, count ≤ 3; AND the
  fused candidate pool differs from the single-query pool for > 0
  questions (pool-difference count recorded).
- decompose: the report must record how many of the 60 questions
  triggered the heuristic. **If zero trigger, the arm is recorded as NOT
  EXERCISED — explicitly distinct from "no win"** — and the decision for
  that arm is "insufficient evidence, default stays disabled", with the
  trigger-shape gap noted as a heldout-set TODO rather than a technique
  verdict.

If no arm passes: ADR becomes **Accepted (with data)**, default stays
`"disabled"`, the no-win is recorded with the table, and the reopen
triggers below stand.

## Decision

Pending the eval arm. The implementation ships **config-off** (`"disabled"`
default), merged and config-selectable, eval-gated — the ADR-0014/0020
rollout pattern. Truthful failure: selecting `multi_query`/`both` without
the `llm_*` provider settings fails at startup in the search-runtime
construction (no silent fallback, mirrors the reranker/LLM/contextualizer
wiring); `decompose` alone requires no LLM and must not demand one.

## Consequences

### Positive

- Attacks candidate generation, the one retrieval stage no measured lever
  has touched; composes with (does not replace) the reranker and any
  future BM25-side work.
- RRF fusion and the rerank-then-expand pipeline are reused unchanged —
  the expansion only widens the rank-list input to fusion.
- Exact/quoted routes and the disabled path stay byte-identical (pinned
  by tests).

### Negative

- multi_query puts an LLM round-trip on the gated search hot path
  (~3 s expected on ppq — see Cost expectation); per-search cost scales
  with traffic, unlike E2's one-time ingest cost.
- Paraphrase quality is unaudited at runtime (no verifier on rewrites); a
  bad paraphrase can only dilute via RRF rank-summing, not override the
  original query's lists, but dilution is exactly what the recall guard
  and ranking bars measure.
- decompose's heuristic is deliberately narrow; it will under-trigger
  (recorded, not hidden — see positive controls).

## Reopen triggers

1. **Local low-latency LLM serving** (or a fast paraphrase-capable small
   model joining the stack post-freeze): re-measure multi_query latency —
   quality verdicts stay valid, the latency bar is the expected blocker.
2. **Heldout set gains a real multi-hop subset** (the decompose heuristic's
   target shape): re-run the decompose arm before citing its verdict.
3. **E2 reopen fires** (real-BM25 eval arm or book corpus): query
   understanding interacts with lexical retrieval — re-measure passing or
   near-bar arms on the upgraded rig.
4. **Baseline shift** (reranker flip via ONNX path, corpus change):
   stale lifts must be re-measured before citing this ADR.

## References

Access date 2026-06-11.

- Master plan E3 spec — `docs/superpowers/plans/2026-06-10-sota-master-plan.md` ("### E3")
- Committed baseline — `tests/eval/reports/retrieval_baseline.json`
- Rollout/rule precedents — ADR-0014 (enablement measurement), ADR-0020 (frozen-rule bake-off, positive controls)
- RRF fusion — `apps/api/app/services/retrieval/fusion.py` (reciprocal rank fusion, k=60)
- Route gate — `apps/api/app/services/retrieval/router.py` (ADR-0008 latency tiers)
