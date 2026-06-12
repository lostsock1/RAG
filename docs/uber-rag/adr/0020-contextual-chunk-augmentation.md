# ADR-0020: Contextual Chunk Augmentation (Breadcrumb + LLM Arms)

Status: **Proposed — decision rule frozen 2026-06-11, bake-off pending.**
This ADR is committed *before* the measurement per house discipline (the
rule must not be shaped by the numbers it judges). The bake-off table and
the final Accepted-with-arm / Accepted-with-data outcome will be appended
below without altering the frozen rule.
Date: 2026-06-11

## Context

Retrieval's measured weakness is **ranking, not recall**. The committed
post-distractor baseline (60 heldout questions, C5 corpus + 8 same-topic
hard-negative docs, BGE-M3 dense, parent expansion ON, reranker off) is:

- **MRR@10 0.8337, nDCG@10 0.8754, recall@10 1.000**
  (`tests/eval/reports/retrieval_quality.json`)

recall@10 is saturated at 1.000 by design — the distractors push true
evidence down a few ranks, never past k. The master plan's suggested E2
margin (≥ +0.03 recall@10) predates the distractor corpus and is therefore
**unachievable and void**; this ADR judges on ranking lift instead.

The one in-freeze ranking lever already measured — enabling
`bge-reranker-v2-m3` (ADR-0014) — cleared the quality bar (+0.0413 MRR@10)
but stays blocked on query-time latency (~2.2 s overhead vs the 1 s bar).
Contextual augmentation attacks the same ranking weakness from the other
side: it spends **ingest-time** cost instead of query-time latency, so the
ADR-0014 latency blocker structurally cannot apply here.

Mechanism: chunks are embedded and BM25-indexed out of context ("the second
law states…" — of what document? which section?). Same-topic confusables
collide because the chunk text alone does not say where it came from.
Augmentation prepends a short situating prefix to the chunk's *search
representation* (`Chunk.search_text = context_prefix + "\n" + text`) while
the stored `text` stays verbatim for display, citation, and verification.

### Technique sources (entry gate verified 2026-06-11)

1. **Anthropic Contextual Retrieval** (Tier 2,
   <https://www.anthropic.com/news/contextual-retrieval>): one LLM call per
   chunk with the whole document in context, asking for a 50–100-token
   situating context, prepended before embedding AND BM25. Reported top-20
   retrieval **failure-rate reductions: 35%** (5.7% → 3.7%, contextual
   embeddings only), **49%** (→ 2.9%, + contextual BM25), **67%** (→ 1.9%,
   + reranking). Cost reported at $1.02 per million document tokens *with
   prompt caching* — ppq.ai has **no** prompt caching, so our cost scales
   linearly with (document tokens × chunks); acceptable at fixture scale,
   a real cost line for production books.
2. **Jina late chunking** (Tier 1, arXiv:2409.04701) — the architectural
   alternative **not** chosen. Different mechanism: embed the long text
   once, then pool token embeddings into chunk embeddings afterward, so
   each chunk vector absorbs document context "for free" (no per-chunk LLM
   calls). Rejected because: (a) it only helps the dense side — BM25 gains
   nothing, while prefix augmentation feeds both arms of hybrid retrieval;
   (b) it bypasses our chunk-persistence/index pipeline (chunk vectors
   would no longer be derivable from persisted chunk rows, breaking the
   re-embed/reindex path and the stub-embedder determinism tests); (c) it
   requires long-context mean-pooling inference through the embedder seam
   that `BgeM3Embedder` (FlagEmbedding encode path) does not expose today.
   BGE-M3 the *model* could support it; recorded as a credible GPU/E4-era
   revisit, not a current candidate.

### Arms under test

- **breadcrumb** (no-LLM, near-free): prefix = document title + heading
  path + page anchor, e.g. `"Physics Textbook Ch3 Thermodynamics > Entropy
  (p. 5)"` (`app/services/contextualizers/breadcrumb.py`). Uses only
  structural fields already persisted on chunks. Freeze-trivial,
  air-gap-free, zero marginal cost.
- **llm**: Anthropic recipe verbatim (`contextualizers/llm.py`,
  `_PROMPT_TEMPLATE`), one ppq.ai `Llama-3.3-70B-Instruct` completion per
  leaf chunk at ingest, 12 000-char document budget, max_tokens 128,
  temperature 0. Calibrated 2026-06-11: the 27-doc eval corpus yields
  **313 leaf chunks**; one real call ≈ **3.06 s** with sane output → ≈
  **16 min serial** per full corpus ingest. Persisted with the chunk
  (`chunks.context_prefix`), so the cost is one-time and idempotent —
  re-runs skip via the completed-stage guard.

Both arms are models-freeze-compatible (2026-06-11 directive): breadcrumb
calls no model; llm reuses the existing frozen answering LLM through the
existing OpenAI-compatible seam. No new model enters the stack.

## Decision rule (FROZEN before measurement)

Measured on the C3 rig, 60 heldout questions, against the committed
post-distractor baseline above. Three arms: baseline (unaugmented),
breadcrumb, llm. Augmented arms re-ingest the corpus through their own
eval stack (embedding input changes; the session-scoped `eval_stack`
fixture stays byte-identical for baseline reproducibility).

**Adopt an arm as production default iff all of:**

1. **Ranking lift:** MRR@10 lift ≥ **+0.02** OR nDCG@10 lift ≥ **+0.02**
   over the committed baseline (MRR@10 0.8337 / nDCG@10 0.8754), and
2. **Recall guard:** recall@10 drop ≤ **0.02** (from 1.000), and
3. **Cost acknowledged:** the arm's ingest cost is recorded in this ADR
   (breadcrumb ≈ 0; llm ≈ 3 s/chunk via ppq, one-time, persisted).

**Tie-breaker (frozen):** if both arms pass, **breadcrumb wins** unless
llm's lift exceeds breadcrumb's by ≥ **+0.02** on the deciding metric —
the LLM arm must justify its nonzero ingest cost, network dependency, and
air-gap friction with a bar-sized *additional* lift, not a rounding error.

**Positive control (mandatory, E1 lesson):** each augmented arm's run must
prove augmentation actually happened — assert `contextualized_count` > 0
(expected ≈ 313), ≥ N chunks persisted with non-empty `context_prefix`,
and `search_text != text` for those chunks. A silently unaugmented arm
would fraudulently reproduce the baseline and read as "no lift".

**Latency posture:** this is ingest-time work; the query-time VPS latency
caveat (ADR-0014's blocker) does not apply. The flip decision does not
wait on VPS re-verification; the ingest cost line above is the honest
price instead.

If no arm passes: ADR becomes **Accepted (with data)**, default stays
`disabled`, the no-win is recorded with the table, and the reopen triggers
below stand.

## Decision

Pending the bake-off. The implementation (landed 2026-06-11, disabled-path
bit-identical, suite 511/3) ships **config-off**:
`contextual_augmentation: Literal["disabled","breadcrumb","llm"] =
"disabled"` — exactly the ADR-0014 rollout pattern: merged, selectable,
eval-gated, default off until the frozen rule passes.

## Consequences

### Positive

- A ranking lever that costs ingest time instead of query latency — the
  only dimension ADR-0014's reranker cannot trade on.
- Both hybrid arms benefit (dense via embed input, BM25 via the indexed
  `text` field); display/citation/verification text stays verbatim
  (`display_text` mapping in OpenSearch, Qdrant payload unchanged).
- Disabled path is byte-identical (7 stages, `search_text == text`),
  pinned by tests — zero risk to the shipped default while off.

### Negative

- **Reindex implication:** augmentation changes the embedding/BM25 input,
  so corpora ingested before enablement must be **re-ingested** to gain
  (or to stay consistent with) the new representation. Eval fixtures
  re-ingest trivially; for real corpora the E4 reindex CLI is the
  production path — enabling the flag before E4 lands means new and old
  corpora coexist with different search representations.
- LLM arm adds a real per-corpus ingest cost (≈ 3 s/chunk serial on ppq,
  no caching) and a network dependency at ingest time; breadcrumb does
  not, which is why the tie-breaker favors it.
- One more pipeline stage (8 vs 7) when enabled; stage-skip idempotency
  must hold (covered by tests).

## Reopen triggers

1. **Corpus shift:** a production corpus with deep structure (books) shows
   ranking failures attributable to out-of-context chunks even after this
   ADR's outcome — re-run the bake-off on a corpus slice from that domain.
2. **Prompt caching becomes available** on the generation provider (or a
   local LLM serves ingest): the llm arm's cost line collapses toward
   Anthropic's $1.02/Mtok figure — re-weigh the tie-breaker.
3. **Late chunking unlocks:** GPU-era serving or an embedder seam that
   exposes long-context token pooling (E4+) makes arXiv:2409.04701 a
   live alternative — revisit as a separate ADR; it composes with, rather
   than replaces, BM25-side augmentation.
4. **E3 query understanding** lands and changes the ranking baseline
   materially — stale lifts must be re-measured before citing this ADR.

## References

Access date for all external sources: 2026-06-11.

- Anthropic Contextual Retrieval — <https://www.anthropic.com/news/contextual-retrieval>
- Jina late chunking — arXiv:2409.04701 — <https://arxiv.org/abs/2409.04701>
- Committed baseline report — `tests/eval/reports/retrieval_quality.json`
- Reranker arm precedent (rule shape, rollout pattern) — `docs/uber-rag/adr/0014-reranker-selection-phase-4.md`
- Implementation: `apps/api/app/services/contextualizers/`, `app/workflows/stages.py` (`run_contextualize_stage`), migration `20260611_0010_chunk_context_prefix`
