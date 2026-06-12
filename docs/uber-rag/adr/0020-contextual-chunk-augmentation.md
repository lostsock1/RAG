# ADR-0020: Contextual Chunk Augmentation (Breadcrumb + LLM Arms)

Status: **Accepted (with data), 2026-06-11** — frozen rule applied
mechanically to the bake-off: **neither arm passes; `contextual_augmentation`
default stays `"disabled"`**. Breadcrumb lifts ranking in the right direction
but below the bar (MRR@10 +0.0090, nDCG@10 +0.0065); the LLM arm actively
*hurts* on the distractor corpus (MRR@10 −0.0867, nDCG@10 −0.0686). Both arms
remain merged and config-selectable; the implementation, tests, and wiring
stay (the 8-stage augmented path is fully covered). See "Measurement results"
below. The decision rule was frozen and committed before measurement
(`3941a40`) and was not altered.
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

**No arm is adopted; the default stays `"disabled"`** (frozen rule applied
to the 2026-06-11 bake-off — see Measurement results). The implementation
(disabled-path bit-identical, suite green) stays merged and
config-selectable: `contextual_augmentation:
Literal["disabled","breadcrumb","llm"] = "disabled"` — exactly the ADR-0014
rollout pattern: merged, selectable, eval-gated, default off because the
frozen rule did not pass.

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

## Measurement results (2026-06-11)

Report: `tests/eval/reports/retrieval_contextual_augmentation.json`
(60 evidence-backed heldout questions, 27-doc corpus incl. the 8 C5
distractors, dense-only rig — stub lexical retriever, stub reranker, parent
expansion off, i.e. the committed-baseline retrieval shape; each arm
re-ingested the corpus through its own isolated SQLite + in-memory-Qdrant +
BGE-M3 stack).

**Positive control (both arms): 313/313 leaf chunks contextualized and
persisted with non-empty `context_prefix`, `search_text != text` for all
313** — the outcome below is a real measurement of augmentation, not a
silent no-op reproducing the baseline.

| metric | baseline (committed) | breadcrumb | lift | llm | lift |
|---|---|---|---|---|---|
| MRR@10 | 0.8337 | 0.8427 | **+0.0090** | 0.7470 | **−0.0867** |
| nDCG@10 | 0.8754 | 0.8819 | **+0.0065** | 0.8068 | **−0.0686** |
| recall@5 | 0.9833 | 0.9667 | −0.0166 | 0.9500 | −0.0333 |
| recall@10 | 1.000 | 1.000 | 0.0 | 0.9833 | −0.0167 |
| ingest cost | — | 56 s corpus-wide (~0) | | 1428 s (**4.56 s/leaf** × 313, ppq serial) | |

**Frozen-rule application:** breadcrumb fails the ranking-lift bar (both
lifts < +0.02; recall guard ok). The llm arm fails everything it can fail:
ranking strongly negative, recall@10 −0.0167 (within the guard but
negative), and it is the costly arm. `adopt_arm = null` → **default stays
`"disabled"`**.

**Why the LLM arm hurt (analysis, not excuse):** the recipe's situating
context is *topic-level* ("Description of the second law of
thermodynamics…"), and the C5 distractor corpus is built precisely from
same-topic confusables. Prepending generic topic words to every chunk pulls
same-topic chunks *closer together* in embedding space — the opposite of
what ranking on this corpus needs — while diluting the chunk's specific
content. Anthropic's reported gains came from long multi-section documents
where a chunk is ambiguous *within* its own document; our fixture docs are
short and single-page, so the chunk already carries most of its context.
The breadcrumb arm (title disambiguation) is directionally right and cheap,
just sub-significance on a corpus whose titles already differ.

**Measurement scope caveats (recorded in the report):** (a) the rig is
dense-only — the contextual-BM25 share of the technique's reported gain
(35% → 49% failure-rate reduction) is structurally invisible here; (b) the
corpus is short-document; book-profile corpora with deep heading hierarchies
are where breadcrumbs carry real signal. Both are reopen conditions, not
reasons to discount the measured result.

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
5. **The eval rig gains a real lexical (BM25) arm:** the contextual-BM25
   share of the technique — invisible to the 2026-06-11 dense-only
   measurement — becomes measurable. Re-run at least the breadcrumb arm
   (near-free) before relying on this ADR's no-win for hybrid retrieval.

## References

Access date for all external sources: 2026-06-11.

- Anthropic Contextual Retrieval — <https://www.anthropic.com/news/contextual-retrieval>
- Jina late chunking — arXiv:2409.04701 — <https://arxiv.org/abs/2409.04701>
- Committed baseline report — `tests/eval/reports/retrieval_quality.json`
- Reranker arm precedent (rule shape, rollout pattern) — `docs/uber-rag/adr/0014-reranker-selection-phase-4.md`
- Implementation: `apps/api/app/services/contextualizers/`, `app/workflows/stages.py` (`run_contextualize_stage`), migration `20260611_0010_chunk_context_prefix`
