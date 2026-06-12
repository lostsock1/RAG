# HANDOVER — Phase E in progress; E2 foundation landed, resume at ADR-0020 + E2 tests/bake-off (written 2026-06-11, end of fifth session)

For a fresh session continuing the master plan. Read in this order:

1. `AGENTS.md` — startup protocol (mandatory: read PROJECT_STATE.md + TASKS.md first).
2. `docs/superpowers/plans/2026-06-10-sota-master-plan.md` — **the canonical
   forward plan**. Phases A–D carry ✅ COMPLETE blocks; Phase E carries ✅
   blocks for E0a (+ both ADR-0019 follow-ups), E1, the reranker arm, and
   the distractor corpus, plus the dated **DESCOPED** note (models frozen).
   E2's spec is at "### E2 — ADR-0020 + contextual chunk augmentation".
3. `docs/uber-rag/PROJECT_STATE.md` — status header + Recent-changes rows.

## Binding user directive (2026-06-11)

**Models are frozen.** Stay with the current stack: BGE-M3, bge-reranker-v2-m3,
ppq.ai Llama 3.3 70B (MiniCheck verifier variants config-only). The platform
lives on the **CPU-only VPS**, generation via **API calls, no GPU**. E4
bake-offs and E5 are deferred; latency bars are CPU bars; dev-Mac numbers
need VPS re-verification before SLA-relevant defaults ship. E2/E3 proceed on
technique merits via existing seams (both arms below are freeze-compatible).

## Where things stand

Backend suite: **511 passed, 3 skipped** (verified on this exact tree).
Commits: `c3b0f1a` (reranker fix + arm) is **pushed**; `6f875cb` (distractor
corpus) and the E2-foundation handover commit are **local — push only when
the user says "push"**.

Earlier sessions (all recorded in PROJECT_STATE rows): reranker reimplemented
on plain transformers (FlagEmbedding 1.4.0 incompatible with transformers
5.x) and measured — NO FLIP; distractor corpus (8 hard-negative docs) reset
the baseline to **MRR@10 0.834 / nDCG@10 0.875 / recall@10 1.000** and
re-running the reranker arm flipped its quality verdict to PASS (+0.0413
MRR@10), leaving latency as the only blocker (ADR-0014 updated).

## E2 — what THIS session finished (committed, suite-green)

**Entry gate (done — reuse, don't redo).** Both technique sources verified
2026-06-11:

- Anthropic Contextual Retrieval (Tier 2,
  https://www.anthropic.com/news/contextual-retrieval): prepend an
  LLM-generated chunk-situating context (prompt = whole document + chunk,
  "short succinct context… for the purposes of improving search retrieval",
  50–100 tokens) before embedding AND BM25. Reported top-20 retrieval
  failure-rate reductions: embeddings-only 35% (5.7%→3.7%), + contextual
  BM25 49% (5.7%→2.9%), + reranking 67% (5.7%→1.9%). Cost note: $1.02 per
  million document tokens with prompt caching (ppq has no caching — cost
  scales linearly; fine at fixture scale).
- Jina late chunking (Tier 1, arXiv:2409.04701): different mechanism —
  embed the long text once, pool token embeddings into chunk embeddings
  afterward; needs long-context mean-pooling embedder. Relevant to the ADR
  as the architectural alternative NOT chosen (BGE-M3 could support it, but
  it bypasses our chunk-persistence/index pipeline; record as rejected
  alternative with reason).

**LLM-arm calibration (done).** The 27-doc corpus chunks to **313 leaf
chunks** (26 parents). One real ppq contextualization call (Llama 3.3 70B,
the exact recipe prompt) ≈ **3.06 s, sane output** ("Description of the
second law of thermodynamics.") → 313 calls ≈ **16 min serial** at ingest.
This is the eval-arm budget, comparable to existing real-LLM eval runs.

**Implementation foundation (done, disabled-path verified green):**

- Migration `infra/migrations/versions/20260611_0010_chunk_context_prefix.py`
  — nullable `chunks.context_prefix` (Text). Postgres CI's
  alembic-upgrade-head job will exercise it.
- `app/schemas/chunks.py` — `Chunk.context_prefix: str | None = None` +
  **`search_text` property**: `context_prefix + "\n" + text` when present,
  else `text` verbatim (the byte-identity guarantee for the disabled path).
- `app/db/models/chunk.py` — column + `to_schema()` mapping.
- `app/repositories/chunks.py` — `persist_chunks` round-trips the prefix
  (parents + children); new `set_chunk_context_prefixes(prefixes={id: str|None})`
  (idempotent, returns rowcount).
- **New package `app/services/contextualizers/`**: `base.py`
  (`ChunkContextualizer` Protocol + frozen `ContextualizeInput(document_title,
  document_text, leaf_chunks)`), `breadcrumb.py` (no-LLM: "Title > heading >
  path (p. N)"), `llm.py` (`LlmChunkContextualizer`, OpenAI-compatible POST,
  Anthropic recipe prompt verbatim in `_PROMPT_TEMPLATE`, 12 000-char doc
  budget, max_tokens 128, temp 0), `stub.py` (deterministic
  `"[context: <title>]"` for tests).
- `app/workflows/stages.py` — `run_contextualize_stage(...)` (skips when
  already completed; details record `contextualized_count` + `rows_updated`
  — use as the eval positive control); **`run_embed_stage` now embeds
  `c.search_text`** (== `c.text` when unaugmented).
- `app/services/indexers/opensearch_indexer.py` — BM25 `text` field now
  indexes `chunk.search_text`; new un-indexed `display_text` field carries
  the original; `app/services/retrieval/opensearch_retriever.py` maps hit
  text from `display_text` (falls back to `text` for pre-E2 indices).
  Qdrant payload `text` stays `chunk.text` (display) — augmentation reaches
  the dense side only through the embed input, by design.
- `app/core/config.py` —
  `contextual_augmentation: Literal["disabled","breadcrumb","llm"] = "disabled"`,
  `contextual_llm_max_output_tokens: int = 128`.
- `app/workflows/pipeline_runner.py` — optional `contextualizer=` ctor
  param; **dynamic `_stage_names`**: inserts `"contextualize"` before
  `"embed"` ONLY when a contextualizer is injected (disabled pipeline stays
  exactly 7 stages — `test_ingestion_dispatch` asserts `len(stages) == 7`
  and passes); stage call sits between persist_chunks and embed;
  `document_title` captured from the Document row.

**Verified**: full backend suite 511/3 on this tree; targeted 47 tests
(chunks repo, dispatcher, ingestion dispatch incl. the 7-stage assert,
opensearch indexer/retriever, indexers) pass.

## NOT done — resume here, in this order

1. **ADR-0020 (`docs/uber-rag/adr/0020-contextual-chunk-augmentation.md`) —
   write it BEFORE the bake-off and freeze the decision rule in it.**
   House discipline: rule frozen before measurement. The plan's suggested
   margin (≥ +0.03 recall@10) **predates the distractor corpus and is
   unachievable — recall@10 is saturated at 1.000**; judge on ranking lift
   instead. Suggested frozen rule (mirror the reranker arm's): adopt an arm
   as production default iff (MRR@10 or nDCG@10 lift ≥ +0.02 over the
   committed post-distractor baseline) AND recall@10 drop ≤ 0.02 AND added
   ingest cost is acknowledged (breadcrumb ~0; llm ~3 s/chunk ppq, one-time,
   persisted). Breadcrumb beats llm at equal lift (no LLM, air-gap-free).
   Include: context (ranking weakness, distractor-corpus numbers), the two
   sources + their numbers (above), late chunking as rejected alternative,
   cost note, reindex implication (embedding input changes ⇒ corpora must
   re-ingest; E4 reindex CLI is the production path), rollout (config-off,
   eval-gated like ADR-0014).
2. **TDD tests for the new pieces** (the foundation is implementation-first;
   the suite only proves the disabled path didn't regress — the new code
   paths have NO dedicated tests yet). Cover: `search_text` property
   (with/without prefix); breadcrumb output (title+path+page, empty-field
   handling); stub determinism; llm contextualizer against a fake transport
   (prompt contains document + chunk, strips whitespace, None on empty);
   `set_chunk_context_prefixes` round-trip + clearing with None;
   `run_contextualize_stage` (sets prefixes, records counts, skip-if-completed,
   no-leaf short-circuit); pipeline with stub contextualizer → 8 stages,
   prefix persisted, embed receives prefixed text (assert via fake embedder
   capturing texts), OpenSearch `_last_bulk_body` shows `text` augmented +
   `display_text` original; pipeline without contextualizer → 7 stages
   byte-identical (existing tests already pin much of this).
3. **Runtime/production wiring**: nothing constructs a contextualizer from
   `Settings` yet. Find where the app factory / upload path builds
   `InProcessDispatcher` (it passes embedder/indexers — likely
   `app/main.py` or the uploads route module) and inject per
   `settings.contextual_augmentation`: `"breadcrumb"` → BreadcrumbContextualizer;
   `"llm"` → LlmChunkContextualizer from `llm_base_url/llm_api_key/llm_model_name`
   + `contextual_llm_max_output_tokens`, **truthful startup failure** if
   `"llm"` is selected without the llm_* settings (house rule: no silent
   fallback — mirror how `reranker_backend`/`llm_backend` wire in
   `runtime.py`/routes). Temporal path takes the same ctor param via
   `build_temporal_worker`'s PipelineRunner construction — check it.
4. **E2 bake-off on the C3 rig** (`tests/eval/`): three arms — committed
   baseline (unaugmented; already exists), **breadcrumb**, **llm**. The
   augmented arms need their OWN ingestion (embedding input changes), i.e.
   build a second eval stack with `contextualizer=` injected rather than
   reusing `eval_stack` (which must stay byte-identical for baseline
   reproducibility — its conftest docstring says so). Suggested shape: a
   separate module-scoped fixture in the arm test file that stands up
   SQLite+Qdrant-in-memory+BGE-M3 with the contextualizer, mirroring
   `eval_stack` construction (BGE-M3 weights are cached; ~40 s/arm embed
   cost; llm arm adds ~16 min of ppq calls — pin one anyio backend, needs
   `PPQ_API_KEY`). **Positive control mandatory** (E1 lesson): assert
   `contextualized_count == 313`-ish > 0 AND that ≥ N chunks in the DB have
   non-empty `context_prefix` AND `search_text != text` — a silently
   unaugmented arm would fraudulently reproduce the baseline. Report:
   `tests/eval/reports/retrieval_contextual_augmentation.json` with arms,
   lifts vs committed baseline, decision per the ADR's frozen rule.
   Decision: flip `contextual_augmentation` default + ADR Accepted-with-arm
   if a rule passes (VPS caveat does NOT apply — this is ingest-time, not
   query-time; note ingest cost instead), else ADR Accepted-with-data,
   config stays "disabled", record the no-win.
5. **Docs + commit per task**: PROJECT_STATE row + header, TASKS.md E2
   checkbox, master plan E2 ✅ block, HANDOVER refresh.

## Environment & gotchas (this machine)

- Python = conda base (`/opt/homebrew/Caskroom/miniconda/base/bin/python`).
  transformers 5.8.1; FlagEmbedding 1.4.0 stays installed (BGE-M3 embedder
  uses it; the reranker is FlagEmbedding-free — keep it that way, a unit
  test guards it). Weights cached: BGE-M3, NLI deberta, MiniCheck FT5-L +
  RoBERTa-L, bge-reranker-v2-m3.
- `PPQ_API_KEY` set in the shell env; never print it. ppq base URL in use:
  `https://api.ppq.ai/v1`, model `meta-llama/Llama-3.3-70B-Instruct`
  (settings default). ~3 s/call.
- `api.github.com` times out; `github.com`, raw.githubusercontent.com,
  anthropic.com, arxiv.org, HF hub all reachable.
- Eval reports policy: canonical JSON committed under `tests/eval/reports/`;
  numbers without a committed report are not citable. Re-running
  quality/expansion tests rewrites reports with run-specific chunk ids —
  aggregates must stay bit-identical; revert churn unless aggregates
  legitimately changed. Committed baseline = post-distractor numbers
  (MRR@10 0.8337, nDCG@10 0.8754, recall@10 1.000).
- Corpus span-isolation invariant: no fixture doc may contain a heldout
  evidence span verbatim (check before editing corpus docs).
- `persist_chunks` deletes+reinserts on re-run; retries are safe only
  because completed stages skip (`_is_stage_completed`) — do not call
  persist_chunks outside the chunk-stage guard or prefixes get wiped.
- The eval `eval_stack` is session-scoped, byte-identical-baseline-bearing;
  augmented arms build their own stack (see step 4).
- anyio pytest plugin: real-LLM tests must pin one backend or they run twice.
- Commit style: conventional commits, trailer
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; commit per task,
  PROJECT_STATE row per task; push ONLY when the user says "push".

## Verification commands

```bash
python -m pytest apps/api/app/tests/ -q                           # 511 passed, 3 skipped on this tree
python -m pytest tests/eval/test_retrieval_quality.py -q          # baseline (MRR@10 0.8337; aggregates must match committed)
python -m pytest tests/eval/test_retrieval_parent_expansion.py -q # E1 gate
python -m pytest tests/eval/test_retrieval_reranker_arm.py -q -s  # quality_pass=true, flip=false (latency)
python -m pytest apps/api/app/tests/integration/test_ingestion_dispatch.py -q  # 7-stage disabled-path pin
```

Do not regress: post-distractor baseline aggregates, the 7-stage disabled
pipeline (`len(stages) == 7` assertions), OpenSearch `display_text` original
text mapping, ADR-0017 SLA numbers, negative compliance 1.00, ACL leakage,
canary catch-rate, E1 containment-dedupe test, FlagEmbedding-free reranker
guard.
