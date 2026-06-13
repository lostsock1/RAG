# HANDOVER — Phase F: F0+F1 done; F2.1 (profile selection) + F2.4 (PDF page-anchor e2e) DONE; F2.2 (book eval arm) + F2.3 (multi-hop) remain (written 2026-06-13, ninth session)

## Ninth session (2026-06-13) — F2.1 + F2.4 landed

User said "push, then start". The push was a **no-op** — `fde333a` and all
prior eighth-session commits were already on `origin/main` (the eighth-session
note below claiming "NOT pushed" was stale). Then F2.1 + F2.4 landed:

- **F2.1 — profile selection at upload + jobs API + profile-routed chunking**
  (`5f0e451`, **pushed**). Upload takes `profile: loose|book` (default loose),
  snapshotted on `IngestionRun` (migration `20260613_0011`, server_default
  backfills loose) + surfaced in the upload response and jobs list/detail.
  `run_chunk_stage` now routes off the **persisted** run profile
  (`pipeline_runner` reads `claimed_run.profile`) instead of the old
  `source_type != "loose_document"` guess; defensive unknown→loose coerce.
  Loose path byte-identical → committed eval baseline preserved (eval ingests
  default-loose; real-pipeline wiring already exercised by
  `test_ingestion_dispatch.py`). OpenAPI updated. +6 tests; suite **605** non-slow.
- **F2.4 — textbook PDF page-anchor e2e** (`29ad6e4`, committed, **NOT pushed**).
  Committed a digital-born 2-page music-theory PDF
  (`apps/api/app/tests/fixtures/textbook_excerpt.pdf` + `generate_textbook_pdf.py`),
  authored with the already-present **PyMuPDF (`fitz`)** — **no new project dep**
  (test reads the committed PDF, needs only Docling). New `slow` e2e: real
  `DocumentConverter().convert()` → `BookDocumentChunker` proves page anchors
  flow into `page_start`/`page_end` (Ch1→p1, Ch2→p2 — the guarantee pageless
  Markdown can't give). **Real-Docling-PDF finding pinned:** the layout model
  tags every heading `section_header` `level=1` (no font-size→depth), so PDF
  heading_paths are **flat** (one section per heading), unlike the Markdown
  backend's nested chapter→section breadcrumbs. Docling runs default layout+OCR
  on the PDF (heavier, network-touching first run — parked ADR-0006 `auto`
  behavior; PDF text layer makes extraction exact). 1 slow test green (13.6 s).

### NEXT — F2.2 (book eval arm, measurement-sensitive) then F2.3

**F2.2 design (investigated, not yet built):** the eval `eval_stack`
(`tests/eval/conftest.py`) ingests all 27 `sample_corpus/*.md` docs via the
custom `_MarkdownParser` (which emits `blocks=[]`) as **loose**. Book-profile
chunking needs hierarchy blocks, so book-profile eval is currently impossible.
Plan:
1. **Upgrade `_MarkdownParser`** to extract markdown `#/##/###` → `ParsedBlock`
   hierarchy (section_header + text blocks with nested `heading_path`
   breadcrumbs, `level = hashes-1`, single page). Keep `page.text` (full) and
   `tables=[]` UNCHANGED so the **loose chunker is byte-identical** → loose
   baseline preserved (loose ignores `blocks`). Cheap + unit-testable; safe.
2. **Isolated book-profile arm** (E2 `_augmented_stack` pattern: save/restore
   the global `session_factory` bind so the session-scoped `eval_stack`
   baseline is untouched): re-ingest the `category: textbook` corpus docs with
   `profile=book`, run the textbook-category heldout questions, record a NEW
   report under `tests/eval/reports/` (do NOT mutate the committed loose
   baseline `retrieval_quality.json`). This step runs **real BGE-M3 on CPU**
   (~minutes) — the cost item.
   - Markdown book chunks are pageless (page=1); F2.4's PDF already owns the
     page-anchor proof, so the eval arm proves hierarchy-based retrieval.
3. **F2.3** (separate, also expensive): author a real multi-hop heldout subset
   (MultiHop-RAG/MuSiQue/HotpotQA/2Wiki shapes — E3 matched 0/5 current
   `multi_hop`), then **re-run the ADR-0021 decompose arm** (heuristic,
   LLM-free, ~free compute but it's the trigger-2 reopen evidence). Span
   isolation applies to all new corpus/questions.

Baseline-integrity rules still bind: committed report aggregates must stay
bit-identical; new measurements are new reports/arms, never baseline mutations.

## Eighth session (2026-06-13) — what landed (all committed, now on origin/main; house rule: push only when the user says "push")

Commits on top of origin/main: `1029c7b` (pre-Phase-F agent-resource ingestion — AGENTS.md stack table reconciled to ADRs), `eaff143` (Phase F entry gate, live-researched + sourced), `710dace` (F0 — Docling pin + adapter hierarchy extraction). Backend suite **597 passed, 3 skipped** (was 592; +5 F0 tests).

- **Phase F entry gate — DONE** (`docs/uber-rag/research/2026-06-13-phase-f-entry-gate.md`, live WebFetch on Tier-1 sources): (1) **Docling** v2.102.1 current, v2 series, `DoclingDocument` exposes the hierarchy + page anchors; (2) **Next.js** repo pins `^15.3` but stable is **16.2.x** — recommend bumping to 16 at F3 start (small cost at 3 pages: async params, `middleware.ts`→`proxy.ts`, `next lint`→ESLint CLI, Turbopack default; NOT a stack swap so no ADR — planner/user to confirm timing); (3) **Playwright** confirmed over Cypress (used in F4).
- **F0 — DONE**: pinned `docling>=2.102,<3` (`[parsing]` extra → `[ingestion]`), installed **docling 2.102.1 / docling-core 2.82.0**. **Frozen stack intact** (transformers 5.8.1 / torch 2.12 / FlagEmbedding 1.4.0; Docling needs `transformers<5.9.0,>=4.34.0`; only in-range pydantic-settings 2.13→2.14). First real Docling run fixed **3 latent adapter bugs** (empty page text vs real `PageItem`; `blocks=[]` discarding hierarchy; table `export_to_markdown()` missing the `doc` arg). `docling_backend.py` now walks the body tree via `iterate_items()` → per-page prose `text` (loose contract preserved) + rich `blocks` (block_type, page anchor, bbox, heading `level`, `heading_path` breadcrumb). `ParsedBlock` gained `level`+`heading_path` (defaulted, backward-compatible). Docling API pinned by introspection: `SectionHeaderItem.level` = 1-based depth (title = 0); `iterate_items()` walks BODY layer (furniture excluded); `prov[0].page_no`/`bbox.{l,t,r,b}`.

## F1 DONE 2026-06-13 — book chunker + multi-parent persistence (commits `77ef072` + F1 2/2)

1/2: `BookDocumentChunker` (`services/chunkers/book.py`) consumes the F0
`page.blocks` hierarchy → one section parent per `heading_path` group, full
chapter→section breadcrumb on every chunk, page anchors into `page_start/end`,
atomic tables, heading-less degradation; `factory.build_chunker(profile)` routes
BOOK→book else loose (`loose.py` untouched); wired into `run_chunk_stage`; table
blocks carry markdown.
2/2: **`persist_chunks` generalized to multi-parent** — keys the parent_id→DB-id
map on each parent's chunker-assigned `id` (resolved to the DB id after flush);
the `len(parents)!=1` guard is gone, replaced by "every parent with children must
carry an `id`" + a loud error if a child references an unknown parent. `loose.py`
parent now sets `id=parent_id` for the same convention; 5 existing persist tests
migrated off the single-parent special case; 2 new multi-parent persist tests + 1
`slow` real-Docling→book e2e (Markdown: 3 sections→3 parents, atomic table leaf,
breadcrumbs). Suite **610 passed, 3 skipped**.

**Deferred from F1 → F2**: page anchors are unit-proven (`test_book_chunker`), but
the Markdown e2e fixture is pageless, so a real textbook **PDF** fixture is the
only way to prove page anchors end-to-end. No PDF authoring lib is installed
(reportlab/fpdf absent) and Docling heading-detection on a synthetic PDF is
unverified — so a committed digital-born textbook-PDF excerpt (span-isolation-safe;
heldout topics are physics/chem/econ/law/math/biology → pick an unrelated subject)
should land in F2 where the profile-aware eval activates the textbook heldout subset.

## NEXT — F2: profile selection at upload + profile-aware eval (master plan "### F2")

- Upload route/schema gains `profile: Literal["loose","book"] = "loose"`, persisted
  on the ingestion run + visible in the jobs API; `run_chunk_stage` should take the
  document's profile from that (today it derives BOOK from `source_type != "loose_document"`).
- Eval fixtures gain ≥ 2 book documents; activate the textbook heldout subset.
- **Author a real multi-hop heldout subset** sourced from MultiHop-RAG/MuSiQue/
  HotpotQA/2Wiki question shapes (E3's decompose heuristic matched 0/5 current
  multi_hop questions — the recorded trigger-shape gap). Landing it **fires
  ADR-0021 reopen trigger 2**: re-run the decompose arm (heuristic, LLM-free, ~free)
  and record the result. Span-isolation invariant applies.
- Land the deferred textbook **PDF** fixture here for true page-anchor e2e.

---

## Seventh-session handover (Phase E close) follows below.

# (archived) HANDOVER — Phase E within-freeze scope COMPLETE (E3 closed no-win, E4a reindex CLI landed); next is Phase F (written 2026-06-12, end of seventh session)

For a fresh session continuing the master plan. Read in this order:

1. `AGENTS.md` — startup protocol (mandatory: read PROJECT_STATE.md + TASKS.md first).
2. `docs/superpowers/plans/2026-06-10-sota-master-plan.md` — **the canonical
   forward plan**. Phases A–D carry ✅ COMPLETE blocks; Phase E carries ✅
   blocks for E0a (+ ADR-0019 follow-ups), E1, the reranker arm, the
   distractor corpus, E2, **E3**, and **E4a**, plus the dated **DESCOPED**
   note (models frozen) and the dated **Phase E exit assessment**
   (within-freeze scope complete; E4b + E5 deferred, not cancelled, and do
   not block Phase F). Next open work: "## Phase F — Book profile +
   frontend E2E" (start with its entry gate).
3. `docs/uber-rag/PROJECT_STATE.md` — status header + Recent-changes rows.

## Binding user directive (2026-06-11)

**Models are frozen.** Stay with the current stack: BGE-M3, bge-reranker-v2-m3,
ppq.ai Llama 3.3 70B (MiniCheck verifier variants config-only). The platform
lives on the **CPU-only VPS**, generation via **API calls, no GPU**. E4
bake-offs and E5 are deferred; latency bars are CPU bars; dev-Mac numbers
need VPS re-verification before SLA-relevant defaults ship.

## Where things stand

Backend suite: **592 passed, 3 skipped** (verified on this exact tree,
2026-06-12). **Everything is pushed** (user said "push" at session close
2026-06-12): the seventh session's commits `54be1d3` (ADR-0021 rule frozen
pre-measurement), `3e3210d` (E3 seams + 26 tests), `b3370a0` (Settings
wiring, truthful no-creds failure), `a63379f` (E3 bake-off + report + ADR
outcome), `7da1fa0` (E3 docs closeout), `f341566` (E4a reindex CLI +
12 tests), `1bf2dc6` (E4a docs + Phase E exit assessment), and this
handover refresh are all on origin/main. Nothing local-only remains.
House rule unchanged for future sessions: push ONLY when the user says
"push".

## E3 — CLOSED this session (full detail in ADR-0021 / PROJECT_STATE / TASKS)

**Outcome: ADR-0021 Accepted with data — NO WIN on all three arms,
`query_understanding` default stays `"disabled"`.** Rule was frozen and
committed BEFORE measurement (`54be1d3`): flip iff (MRR@10 or nDCG@10 lift
≥ +0.02) AND (recall@10 drop ≤ 0.02) AND (added gated-route P50 ≤ 700 ms);
subset wins record-only; cheaper passing arm wins ties; decompose
zero-trigger = not_exercised ≠ no_win.

- Bake-off (`tests/eval/test_retrieval_query_understanding.py`, report
  `tests/eval/reports/retrieval_query_understanding.json`): arms run on the
  SESSION eval stack (query understanding changes nothing at ingest — no
  isolated re-ingestion needed, unlike E2) via the new
  `eval_stack.retrieval_components` hook; paired no-understander control on
  the same stack gives the latency reference and pool-diff; rig equivalence
  was verified per-question (arms reproduce the committed baseline exactly
  on unperturbed questions).
- **multi_query**: ranking dead flat (MRR@10 −0.0012 / nDCG@10 −0.0008,
  recall flat at 1.000) at **+3030 ms added P50** (bar: 700) — a clean
  technique negative, NOT a no-op: positive control proved 60/60 paraphrase
  calls (3.0/question, 180 total) and 60/60 result sets perturbed.
  Mechanism: recall@10 is saturated at 1.000 (no vocabulary-mismatch
  headroom) and topic-preserving paraphrases retrieve the same C5
  same-topic confusables, so RRF rank-summing re-orders nothing.
- **decompose**: triggered on **1/60** (and 0/5 multi_hop questions — the
  heuristic's shapes don't match the heldout multi-hop phrasings; recorded
  trigger-shape TODO). Its lone firing FULLY fixed h49 (chapter_synthesis,
  twin-clause: MRR@10 0.5→1.0) = the entire +0.0084 aggregate — frozen
  subset-honesty clause: reopen evidence, not a pass. +1.5 ms (~free).
- **both**: +2735 ms AND **lost decompose's h49 fix to RRF paraphrase
  dilution** (chapter_synthesis 0.8333 vs decompose's 1.0; decomposer runs
  first under the shared cap, but the paraphrase rank-lists pulled the
  confusable back above the gold). Composing expanders isn't free even when
  one of them works.
- Everything stays merged + config-selectable: `query_understanding:
  Literal["disabled","multi_query","decompose","both"] = "disabled"`,
  `query_understanding_max_expansions`, seams in
  `services/retrieval/query_understanding.py`, merge in
  `hybrid_retriever.py` (expansions widen fusion input only; rerank scores
  the ORIGINAL query; exact/quoted routes never consult the understander;
  None-path byte-identical), wiring in `runtime.py` (truthful startup
  failure for LLM-backed modes without `llm_base_url`/`llm_api_key`;
  decompose requires none).
- Reopen paths (ADR-0021): local low-latency LLM serving (latency was the
  predicted binding constraint — the ADR-0014 situation); heldout gains
  real multi-hop/comparative questions matching decompose's shapes (its
  per-trigger evidence is positive — h49); E2-reopen rig upgrades
  (real-BM25 arm / book corpus); baseline shift (reranker ONNX flip etc.).

## E4a — DONE this session (reindex CLI; full detail in PROJECT_STATE/TASKS/plan)

`python -m app.cli.reindex --tenant-id … [--document-id …]
[--after-document-id …] [--database-url …]` (`apps/api/app/cli/reindex.py`).
Streams the tenant's documents from Postgres in stable id order, re-embeds
leaf `search_text` (persisted ADR-0020 `context_prefix` honored),
re-upserts Qdrant + OpenSearch with the **current**
`get_document_index_acl_metadata` payload. Idempotent (deterministic ids),
resumable (`--after-document-id`, per-document boundary logged), truthful
failure (no bind / out-of-tenant ids / missing grant), never substitutes
stubs: `build_embedder` = BGE-M3 (frozen ADR-0013),
`build_vector_indexer`/`build_lexical_indexer` map the qdrant_*/
opensearch_* settings — the codebase's FIRST Settings→ingestion-indexer
factories. Acceptance round-trip proven (identical ranked ids+scores,
OpenSearch `_source` equality, idempotent re-run) plus ACL-freshness (a
post-ingest grant reaches the reindexed payload; the ingest-time payload
provably lacks it). 12 integration tests
(`apps/api/app/tests/integration/test_reindex_cli.py`).

**Observed gap (recorded, NOT acted on — out of E4a scope):** production
dispatcher construction (`main.py` + `temporal_worker.
build_pipeline_runner_from_settings`) passes no embedder/indexers, so
`PipelineRunner` defaults to **stubs** — real deployments do not write real
indexes yet (consistent with the VPS not running Qdrant/OpenSearch). When
real index serving ships, wire the new `build_*` factories into both
dispatcher paths (mirror the contextualizer wiring pattern, truthful
failure when unconfigured).

## NEXT — Phase F: book profile + frontend E2E (master plan "## Phase F")

Phase E is exhausted within the freeze (exit assessment recorded in the
plan; E4b + E5 deferred, not cancelled, non-blocking). Phase F starts with
its **entry gate** (researcher): Docling current release notes
(heading/page-anchor extraction fidelity), Next.js 15 App Router stability
check, Playwright vs Cypress for the E2E rig (pick Playwright unless
evidence says otherwise). Then the F-tasks per the canonical spec (book
profile chunking is the first big one — note `persist_chunks` currently
supports single-parent documents only and will need the multi-parent
mapping strategy the docstring flags).

Also live but unscheduled (freeze-compatible): ADR-0014 reranker latency
path — ONNX CPU serving (~5× per the ADR's DeepEye note) and/or smaller
rerank candidate pool; quality already passes on the distractor corpus
(+0.0413 MRR@10), only the 2222 ms CPU overhead blocks the flip.

## Environment & gotchas (this machine)

- Python = conda base (`/opt/homebrew/Caskroom/miniconda/base/bin/python`).
  transformers 5.8.1; FlagEmbedding 1.4.0 stays installed (BGE-M3 embedder
  uses it; the reranker is FlagEmbedding-free — keep it that way, a unit
  test guards it). Weights cached: BGE-M3, NLI deberta, MiniCheck FT5-L +
  RoBERTa-L, bge-reranker-v2-m3.
- `PPQ_API_KEY` set in the shell env; never print it. ppq base URL:
  `https://api.ppq.ai/v1`, model `meta-llama/Llama-3.3-70B-Instruct`
  (settings default). ~3–4.6 s/call measured (E3 added-P50 3030 ms agrees).
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
  persist_chunks outside the chunk-stage guard or context prefixes get wiped.
- The eval `eval_stack` is session-scoped and byte-identical-baseline-
  bearing. Arms that change INGESTION build their own stack (E2 pattern:
  `_augmented_stack` in `test_retrieval_contextual_augmentation.py`,
  save/restore the global `session_factory` bind). Arms that only change
  RETRIEVAL compose services over `eval_stack.retrieval_components`
  (E3 pattern: `_build_service` in `test_retrieval_query_understanding.py`)
  — far cheaper, no re-ingestion.
- anyio pytest plugin: real-LLM tests must pin one backend or they run twice.
- Commit style: conventional commits, trailer
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; commit per task,
  PROJECT_STATE row per task; push ONLY when the user says "push".

## Verification commands

```bash
python -m pytest apps/api/app/tests/ -q                           # 592 passed, 3 skipped on this tree
python -m pytest apps/api/app/tests/integration/test_reindex_cli.py -q  # E4a round-trip gate (12)
PYTHONPATH=apps/api python -m app.cli.reindex --help              # CLI entrypoint smoke
python -m pytest tests/eval/test_retrieval_quality.py -q          # baseline (MRR@10 0.8337; aggregates must match committed; revert id churn)
python -m pytest tests/eval/test_retrieval_parent_expansion.py -q # E1 gate
python -m pytest tests/eval/test_retrieval_reranker_arm.py -q -s  # quality_pass=true, flip=false (latency)
python -m pytest apps/api/app/tests/integration/test_ingestion_dispatch.py -q  # 7-stage disabled / 8-stage augmented pins
# E3 bake-off re-run (~8 min, ~120 ppq calls; needs PPQ_API_KEY) — only with intent:
# python -m pytest tests/eval/test_retrieval_query_understanding.py -q -s
# E2 bake-off re-run (expensive: ~25 min, ~313 ppq calls) — only with intent:
# python -m pytest tests/eval/test_retrieval_contextual_augmentation.py -q -s
```

Do not regress: post-distractor baseline aggregates, the 7-stage disabled
pipeline (`len(stages) == 7` assertions) and the 8-stage augmented pin,
OpenSearch `display_text` original-text mapping, ADR-0017 SLA numbers,
negative compliance 1.00, ACL leakage, canary catch-rate, E1
containment-dedupe test, FlagEmbedding-free reranker guard, truthful
startup failure for `contextual_augmentation="llm"` without creds AND for
`query_understanding` LLM-backed modes without creds, understander=None
byte-identical retriever path, exact/quoted routes never consulting the
understander, E4a reindex round-trip identity + ACL-freshness +
out-of-tenant refusal.
