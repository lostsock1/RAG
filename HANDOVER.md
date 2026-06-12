# HANDOVER — Phase E: E2 CLOSED (no win); next task is E3 query understanding (written 2026-06-11, end of sixth session)

For a fresh session continuing the master plan. Read in this order:

1. `AGENTS.md` — startup protocol (mandatory: read PROJECT_STATE.md + TASKS.md first).
2. `docs/superpowers/plans/2026-06-10-sota-master-plan.md` — **the canonical
   forward plan**. Phases A–D carry ✅ COMPLETE blocks; Phase E carries ✅
   blocks for E0a (+ ADR-0019 follow-ups), E1, the reranker arm, the
   distractor corpus, and now **E2**, plus the dated **DESCOPED** note
   (models frozen). Next open task: "### E3 — ADR-0021 + query
   understanding: multi-query + decomposition (L)".
3. `docs/uber-rag/PROJECT_STATE.md` — status header + Recent-changes rows.

## Binding user directive (2026-06-11)

**Models are frozen.** Stay with the current stack: BGE-M3, bge-reranker-v2-m3,
ppq.ai Llama 3.3 70B (MiniCheck verifier variants config-only). The platform
lives on the **CPU-only VPS**, generation via **API calls, no GPU**. E4
bake-offs and E5 are deferred; latency bars are CPU bars; dev-Mac numbers
need VPS re-verification before SLA-relevant defaults ship. E3 proceeds on
technique merits via the existing `LlmBackend` seam (freeze-compatible).

## Where things stand

Backend suite: **549 passed, 3 skipped** (verified on this exact tree).
Pushed: up to `c3b0f1a`. **Local-only (push ONLY when the user says
"push")**: `6f875cb` (distractor corpus), `2c21d3a` (E2 foundation),
`3941a40` (ADR-0020 rule frozen pre-measurement), `6c80f7b` (30 E2 tests),
`f92037b` (Settings→contextualizer wiring), `fffb316` (bake-off + ADR
outcome), plus the session-close docs commit after this file.

## E2 — CLOSED this session (full detail in ADR-0020 / PROJECT_STATE / TASKS)

**Outcome: ADR-0020 Accepted with data — NO WIN, `contextual_augmentation`
default stays `"disabled"`.** Rule was frozen and committed BEFORE
measurement (`3941a40`): adopt iff (MRR@10 or nDCG@10 lift ≥ +0.02 over the
committed post-distractor baseline) AND recall@10 drop ≤ 0.02 AND ingest
cost acknowledged; breadcrumb wins ties unless llm adds a further +0.02.

- Bake-off (`tests/eval/test_retrieval_contextual_augmentation.py`, report
  `tests/eval/reports/retrieval_contextual_augmentation.json`): isolated
  re-ingested stacks per arm (NOT `eval_stack` — it stays byte-identical),
  positive control passed both arms (313/313 leaves prefixed,
  `search_text != text`).
- **breadcrumb**: MRR@10 +0.0090 / nDCG@10 +0.0065 — right direction,
  sub-bar; ~56 s corpus ingest (≈ free). **llm**: MRR@10 −0.0867 / nDCG@10
  −0.0686 / recall@10 −0.0167 — actively harmful; 1428 s (4.56 s/leaf, ppq
  serial). Mechanism: topic-level situating context pulls same-topic
  confusables closer in embedding space — exactly the C5 distractor
  structure. Anthropic's gains presume long multi-section docs.
- Recorded reopen triggers (ADR-0020): real-BM25 eval arm (rig is
  dense-only — contextual-BM25 share unmeasured), book-profile corpora
  (deep heading hierarchies), prompt-caching/local-LLM cost collapse, E3
  baseline shift.
- Everything stays merged + config-selectable: migration
  `20260611_0010`, `Chunk.search_text`, `contextualizers/` package
  (breadcrumb/llm/stub + `factory.build_chunk_contextualizer`), optional
  8th `contextualize` stage, OpenSearch `text`=augmented /
  `display_text`=original, wiring in `main.py` AND
  `temporal_worker.build_pipeline_runner_from_settings` (truthful startup
  failure when `"llm"` lacks `llm_base_url`/`llm_api_key`).

## NEXT — E3 (master plan "### E3 — ADR-0021 + query understanding")

Not started. Spec summary: route-gated multi-query (N=3 paraphrases via the
existing `LlmBackend` seam, parallel retrieval, RRF-merge through the
existing `fusion.py`, then rerank) + heuristic decomposition for multi-hop;
config `query_understanding: Literal["disabled","multi_query","decompose",
"both"] = "disabled"`; deterministic stub paraphraser for tests; never on
exact/quoted routes (ADR-0008). Accept: eval-gated like E2 (multi-hop/needle
subsets are where wins should show), P50 search-latency increase ≤ 700 ms on
gated routes measured and recorded, truthful 503 if enabled without an LLM
backend. House discipline learned in E1/E2 applies: **freeze the ADR-0021
decision rule (judge on ranking/recall lift vs the committed post-distractor
baseline) BEFORE measuring, and build the positive control into the arm**
(e.g., assert paraphrase count > 0 and that merged candidate pools differ
from the single-query pool — a silently-disabled arm must not reproduce the
baseline as "no win").

## Environment & gotchas (this machine)

- Python = conda base (`/opt/homebrew/Caskroom/miniconda/base/bin/python`).
  transformers 5.8.1; FlagEmbedding 1.4.0 stays installed (BGE-M3 embedder
  uses it; the reranker is FlagEmbedding-free — keep it that way, a unit
  test guards it). Weights cached: BGE-M3, NLI deberta, MiniCheck FT5-L +
  RoBERTa-L, bge-reranker-v2-m3.
- `PPQ_API_KEY` set in the shell env; never print it. ppq base URL:
  `https://api.ppq.ai/v1`, model `meta-llama/Llama-3.3-70B-Instruct`
  (settings default). ~3–4.6 s/call measured.
- `api.github.com` times out; `github.com`, raw.githubusercontent.com,
  anthropic.com, arxiv.org, HF hub all reachable.
- Eval reports policy: canonical JSON committed under `tests/eval/reports/`;
  numbers without a committed report are not citable. Re-running
  quality/expansion tests rewrites reports with run-specific chunk ids —
  aggregates must stay bit-identical; revert churn unless aggregates
  legitimately changed (verified again this session: re-run reproduced
  MRR@10 0.8337 exactly; churn reverted). Committed baseline =
  post-distractor numbers (MRR@10 0.8337, nDCG@10 0.8754, recall@10 1.000).
- Corpus span-isolation invariant: no fixture doc may contain a heldout
  evidence span verbatim (check before editing corpus docs).
- `persist_chunks` deletes+reinserts on re-run; retries are safe only
  because completed stages skip (`_is_stage_completed`) — do not call
  persist_chunks outside the chunk-stage guard or context prefixes get wiped.
- The eval `eval_stack` is session-scoped, byte-identical-baseline-bearing;
  arms that change ingestion build their own stack and must save/restore the
  global `session_factory` bind (see `_augmented_stack` in
  `tests/eval/test_retrieval_contextual_augmentation.py` for the pattern).
- anyio pytest plugin: real-LLM tests must pin one backend or they run twice.
- Commit style: conventional commits, trailer
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; commit per task,
  PROJECT_STATE row per task; push ONLY when the user says "push".

## Verification commands

```bash
python -m pytest apps/api/app/tests/ -q                           # 549 passed, 3 skipped on this tree
python -m pytest tests/eval/test_retrieval_quality.py -q          # baseline (MRR@10 0.8337; aggregates must match committed; revert id churn)
python -m pytest tests/eval/test_retrieval_parent_expansion.py -q # E1 gate
python -m pytest tests/eval/test_retrieval_reranker_arm.py -q -s  # quality_pass=true, flip=false (latency)
python -m pytest apps/api/app/tests/integration/test_ingestion_dispatch.py -q  # 7-stage disabled / 8-stage augmented pins
# E2 bake-off re-run (expensive: ~25 min, ~313 ppq calls) — only with intent:
# python -m pytest tests/eval/test_retrieval_contextual_augmentation.py -q -s
```

Do not regress: post-distractor baseline aggregates, the 7-stage disabled
pipeline (`len(stages) == 7` assertions) and the 8-stage augmented pin,
OpenSearch `display_text` original-text mapping, ADR-0017 SLA numbers,
negative compliance 1.00, ACL leakage, canary catch-rate, E1
containment-dedupe test, FlagEmbedding-free reranker guard, truthful
startup failure for `contextual_augmentation="llm"` without creds.
