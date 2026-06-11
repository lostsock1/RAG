# HANDOVER — Phase E in progress; reranker arm + distractor corpus closed, resume at E2 (written 2026-06-11, end of fourth session)

For a fresh session continuing the master plan. Read in this order:

1. `AGENTS.md` — startup protocol (mandatory: read PROJECT_STATE.md + TASKS.md first).
2. `docs/superpowers/plans/2026-06-10-sota-master-plan.md` — **the canonical
   forward plan**. Phases A–D carry ✅ COMPLETE blocks; Phase E carries ✅
   blocks for E0a (+ both ADR-0019 reopen follow-ups), E1, the reranker
   arm, and the distractor corpus, plus the dated **DESCOPED** note (models
   frozen).
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

All on `main`. Backend suite: **511 passed, 3 skipped**
(`python -m pytest apps/api/app/tests/ -q`). The reranker fix is pushed
(`c3b0f1a`); the distractor-corpus commit is local unless the user has said
"push" (push only when they do).

### This session — distractor corpus (C5 caveat resolved)

8 same-topic hard-negative docs added under
`tests/eval/fixtures/sample_corpus/` (EN×6: physics/chem/econ/law/math/bio
study-guides; + `de_pruefungsleitfaden`, `pt_guia_de_estudo`). Each section
echoes a target query's **exact subject phrase** ("The gravitational
constant G…", "Inflação é medida por…") but states a **sibling fact** (a
neighbouring constant / definition / element) and contains **no evidence
span** — verified programmatically across all 60 spans (a distractor that
contained a span would silently join its relevance group and defeat the
purpose). Key lesson: the first attempt used sibling *terms* (deflation vs
inflation) and BGE-M3 distinguished them easily (MRR moved −0.002);
**echoing the query's exact phrasing is what creates dense-retrieval
confusion** (MRR moved −0.093).

Outcome — baseline re-measured and **superseded** (corpus now 27 docs):
- **MRR@10 0.927 → 0.834, nDCG@10 0.944 → 0.875, nDCG@5 0.939 → 0.870.**
  Recall@10 stays **1.000** by design — confusables push true evidence down
  a few ranks, not past k; ranking (the measured weakness) now has headroom,
  recall does not (recall headroom would need far higher distractor density,
  deferred — recall was never the weakness). EN MRR 0.898→0.785, DE 1.0→0.929,
  PT held 1.0 (BGE-M3 ranks the PT evidence very robustly).
- **The reranker arm, re-run against the harder baseline, now CLEARS the
  quality bar**: MRR@10 +0.0413, nDCG@10 +0.0314 (both > +0.02), recall flat
  → `quality_pass=true`, recovering ~half the introduced headroom
  (MRR→0.875, nDCG→0.907). Flip still blocked on latency alone (2222 ms
  overhead vs 1000 ms bar). The easy-corpus "+0.013, not worth it" verdict
  was a saturation artifact; ADR-0014's reopen now rests on the latency path
  only (ONNX / smaller candidate pool). ADR-0014 updated with this.
- Reports re-baselined and mutually consistent (baseline aggregates ==
  reranker `baseline_reference`): `retrieval_baseline.json` (gained a
  test-owned `corpus` descriptor), `retrieval_parent_expansion.json`
  (re-passes, positive control 1200 parent rows), `retrieval_reranker_arm.json`.
  Ingestion fixture 3 passed (27-doc count guard auto-adjusts).

### Earlier this day (commit `c3b0f1a`, pushed) — reranker arm closed:

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

## NEXT — E2: ADR-0020 contextual augmentation (resume here)

The distractor corpus removed the blocker — the new baseline (MRR@10 0.834,
nDCG@10 0.875, recall@10 still 1.000) has **ranking headroom**, so a
recall-flat technique can still show a defensible win when judged on
nDCG/MRR lift. **Judge E2 on ranking lift vs the new baseline, not recall**
(recall stays saturated; that was never the weakness).

**Order, per the plan**:

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
python -m pytest tests/eval/test_retrieval_quality.py -q       # baseline arm (~38 s warm; MRR@10 0.834 — harder corpus; aggregates must match committed)
python -m pytest tests/eval/test_retrieval_parent_expansion.py -q  # E1 gate (passes; no regression vs baseline)
python -m pytest tests/eval/test_retrieval_reranker_arm.py -q -s   # reranker arm (~3.5 min; quality_pass=true, flip_default=false on latency)
python -m pytest tests/eval/test_hallucination_canaries.py -q  # canary guard (CPU, models cached)
```

Do not regress: retrieval baseline aggregates (now the **post-distractor**
numbers: MRR@10 0.834 / nDCG@10 0.875 / recall@10 1.000 — a future corpus
change may reset them again, intentionally), the corpus span-isolation
invariant (no distractor doc may contain a heldout evidence span — re-check
with the one-off script in this session's notes if you touch the corpus),
ADR-0017 SLA numbers, negative compliance 1.00, ACL leakage tests, canary
catch-rate assertions, E1 containment-dedupe regression test, the
FlagEmbedding-free reranker guard
(`test_bge_reranker_does_not_import_flagembedding`).
