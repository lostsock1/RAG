# HANDOVER — Phase E in progress; reranker arm closed (NO FLIP), resume at the distractor corpus (written 2026-06-11, end of third session)

For a fresh session continuing the master plan. Read in this order:

1. `AGENTS.md` — startup protocol (mandatory: read PROJECT_STATE.md + TASKS.md first).
2. `docs/superpowers/plans/2026-06-10-sota-master-plan.md` — **the canonical
   forward plan**. Phases A–D carry ✅ COMPLETE blocks; Phase E carries ✅
   blocks for E0a (+ both ADR-0019 reopen follow-ups), E1, and the reranker
   arm, plus the dated **DESCOPED** note (models frozen).
3. `docs/uber-rag/PROJECT_STATE.md` — status header + Recent-changes rows.

## Binding user directive (2026-06-11)

**Models are frozen.** Stay with the current stack: BGE-M3, bge-reranker-v2-m3,
ppq.ai Llama 3.3 70B (MiniCheck verifier variants config-only). The platform
lives on the **CPU-only VPS** for testing and building, generation via **API
calls, no GPU**. Consequences (recorded in the plan + PROJECT_STATE
assumptions + auto-memory): E4's conditional embedder/reranker bake-offs and
E5's answering-LLM bake-off are deferred; the Phase E researcher entry gate
reduces to technique sources; latency bars are CPU bars and dev-Mac numbers
need VPS re-verification before SLA-relevant defaults ship.

## Where things stand

All on `main`, **NOT pushed** (push only when the user says "push").
Backend suite: **511 passed, 3 skipped** (`python -m pytest apps/api/app/tests/ -q`).

This session (after handover commit `5d048fd`) closed the reranker arm:

- **Reranker unblocked**: `BgeRerankerV2M3`
  (`apps/api/app/services/retrieval/bge_reranker.py`) reimplemented on plain
  transformers — `AutoModelForSequenceClassification` + `AutoTokenizer`,
  official model-card scoring (one raw relevance logit per (query, passage)
  pair, batched, `max_length=512`, ordering-only consumption). Class
  interface/config unchanged (`runtime.py` construction site untouched).
  Reason: FlagEmbedding 1.4.0's reranker calls
  `tokenizer.prepare_for_model`, removed for slow tokenizers in
  transformers 5.x — the old path crashed on first real rerank while the
  unit suite stayed green on a monkeypatched fake. TDD 4 red → 5 green;
  `test_bge_reranker.py` now includes a FlagEmbedding-free source guard.
  Real-model smoke: relevant +1.87 > partial −6.63 > irrelevant −11.03.
- **Arm measured, frozen rule applied — NO FLIP**
  (`tests/eval/reports/retrieval_reranker_arm.json`, canonical): quality
  MRR@10 0.9270→0.9403 (+0.0132), nDCG@10 0.9440→0.9554 (+0.0109) — both
  below the +0.02 bar (h04/h16 fixed rank 4→1; h12/h19 regressed 1→2;
  recall@10 flat 1.000, recall@5 saturated to 1.000); latency stub 157 ms
  vs real 2593 ms mean (P95 4084 ms) = **+2436 ms/query vs the 1000 ms
  bar**, on dev-Mac CPU which is optimistic vs the VPS. The latency failure
  is corpus-independent. **`reranker_backend` default stays `"disabled"`.**
  Reopen paths recorded in ADR-0014's enablement-measurement note:
  distractor corpus (quality side); ONNX CPU serving (~5× per the ADR's
  DeepEye figures: ~400–530 ms/20 pairs) and/or smaller rerank candidate
  pool (latency side) — same model, freeze-compatible, unscheduled.
- Gates re-run green: retrieval baseline + E1 expansion arm — aggregates
  bit-identical to committed reports (run-specific chunk-id churn reverted,
  per policy).

## NEXT — distractor corpus (resume here)

**Why it gates everything**: the C5 caveat binds harder than ever. The
16-doc corpus is topically distinct; recall@5/10/20 are all saturated at
1.000 and the reranker arm showed sub-bar lifts on near-ceiling baselines
(nDCG@10 0.944, MRR@10 0.927). No further ranking/recall technique (E2
contextual augmentation, E3 query understanding, any future reranker
re-measurement) can show a defensible win on this corpus.

**Shape** (C5 pattern, all infrastructure exists): author near-duplicate /
same-topic distractor fixture docs into `tests/eval/fixtures/sample_corpus/`
+ evidence blocks in `docs/uber-rag/eval/heldout-v1.yaml` (verbatim-quote
spans, rot-guarded loader asserts — `tests/eval/test_ingestion_fixture.py`
and `apps/api/app/tests/unit/test_eval_harness_loader.py` enforce). Aim:
distractors that share topic/vocabulary with existing evidence docs so
dense retrieval has real confusable candidates (same-topic different-fact
docs, near-duplicate paragraphs with altered specifics, cross-language
near-misses for the DE/PT subsets). After authoring: re-run
`tests/eval/test_retrieval_quality.py` to commit a **new baseline** (the
old `retrieval_baseline.json` aggregates will legitimately drop — that is
the point; keep the old report in git history, note the corpus change in
the report payload + PROJECT_STATE), then the reranker arm can be
re-measured against the new baseline if desired (quality side only — the
latency bar still fails on this hardware).

**Then, in order**:

1. **E2 — ADR-0020 contextual augmentation** (ADR first, docs-only):
   breadcrumb arm (no LLM) + llm arm via the existing ppq seam — both
   freeze-compatible. Technique sources for the ADR: Anthropic
   contextual-retrieval post (Tier 2), Jina late-chunking arXiv:2409.04701
   (Tier 1).
2. **E3 — ADR-0021 query understanding** (existing LLM seam, route-gated).
3. **E4 — reindex CLI only** (bake-offs deferred). **E5 deferred** (freeze).

## Environment & gotchas (this machine)

- Python = conda base (`/opt/homebrew/Caskroom/miniconda/base/bin/python`),
  no `.venv`. transformers **5.8.1**, FlagEmbedding **1.4.0** (still
  installed — the BGE-M3 *embedder* uses it and works; only the reranker
  path was broken and is now FlagEmbedding-free). Weights cached: BGE-M3,
  NLI deberta, MiniCheck FT5-L + RoBERTa-L, bge-reranker-v2-m3 (~2.2 GB).
- `PPQ_API_KEY` is set in the shell env (real-LLM tests skip without it;
  ~60 calls ≈ 15–18 min for the grounding faithfulness suite). Never print it.
- `api.github.com` times out; `github.com` + raw.githubusercontent.com work.
  HF hub + HF API (`curl https://huggingface.co/api/models/<repo>`) work —
  Tier-1 fallback.
- Eval reports policy: canonical JSON committed under `tests/eval/reports/`;
  `*.log` gitignored. Numbers without a committed report are not citable.
  Re-running quality/expansion tests rewrites their reports with
  run-specific chunk ids — aggregates must stay bit-identical; revert the
  churn (`git checkout -- tests/eval/reports/<file>`) unless aggregates
  legitimately changed.
- The eval fixture's `eval_stack` is session-scoped and exposes THREE
  services: `search_service` (baseline arm, expansion stubbed OFF),
  `search_service_parent_expansion` (E1 production shape),
  `search_service_real_reranker` (now actually works).
- Nightly eval CI (`.github/workflows/eval.yml`) runs retrieval_quality,
  negative_populated_corpus, hallucination_canaries — the arm tests
  (reranker, parent-expansion) are on-demand only, NOT in CI.
- anyio pytest plugin: real-LLM tests must pin one backend or they run twice.
- Commit style: conventional commits, trailer
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; commit per task,
  PROJECT_STATE row per task, push only when the user says "push".

## Verification commands

```bash
python -m pytest apps/api/app/tests/ -q                        # backend suite (expect 511/3 skipped)
python -m pytest tests/eval/test_retrieval_quality.py -q       # baseline arm (~35 s warm; aggregates must match committed)
python -m pytest tests/eval/test_retrieval_parent_expansion.py -q  # E1 gate (passes)
python -m pytest tests/eval/test_retrieval_reranker_arm.py -q -s   # reranker arm (~3.5 min; passes, report = NO FLIP)
python -m pytest tests/eval/test_hallucination_canaries.py -q  # canary guard (CPU, models cached)
```

Do not regress: retrieval baseline aggregates (until the distractor corpus
intentionally resets them), ADR-0017 SLA numbers, negative compliance 1.00,
ACL leakage tests, canary catch-rate assertions, E1 containment-dedupe
regression test, the FlagEmbedding-free reranker guard
(`test_bge_reranker_does_not_import_flagembedding`).
