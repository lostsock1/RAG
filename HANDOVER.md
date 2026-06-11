# HANDOVER — Phase E in progress; resume at the reranker arm fix (written 2026-06-11, end of second session)

For a fresh session continuing the master plan. Read in this order:

1. `AGENTS.md` — startup protocol (mandatory: read PROJECT_STATE.md + TASKS.md first).
2. `docs/superpowers/plans/2026-06-10-sota-master-plan.md` — **the canonical
   forward plan**. Phases A–D carry ✅ COMPLETE blocks; Phase E now carries
   ✅ blocks for E0a (+ both ADR-0019 reopen follow-ups) and E1, plus a dated
   **DESCOPED** note under the Phase E entry gate (models frozen).
3. `docs/uber-rag/PROJECT_STATE.md` — status header + Recent-changes rows for
   everything below.

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
Backend suite: **507 passed, 3 skipped** (`python -m pytest apps/api/app/tests/ -q`).

Session commits (after handover commit `f04200a`):

- **E0a answer-style fix** (`1f41e40`): prompt blocks render
  `[Source N: title — heading path, page(s)]` instead of machine
  `rank=`/`citation_id=`/`chunk_id=` headers (citations are verifier-attached,
  never parsed from answers — verified before removal); `SYSTEM_INSTRUCTION`
  gained an anti-parroting/meta-discourse rule scoped to answered questions.
- **ADR-0019 c1 re-measured** (`23a2c41`): grounding faithfulness
  **0.578 → 0.9007** on fresh answers (60/60) — criterion 1 flipped to PASS;
  meta-discourse rejection class eliminated; rejection then stood on c3 alone.
- **ADR-0019 c3 path executed — rejection CONFIRMED** (`0a11d04`):
  `GroundingAnswerVerifier` gained the sequence-classification recipe
  (verified against upstream MiniCheck: single-string `chunk</s>claim`,
  512-token window, doc chunked to max_len−300, max-aggregation);
  MiniCheck-RoBERTa-Large measured offline on the identical persisted answers
  (zero LLM calls): c1 0.7632 FAIL / c2 1.00 PASS / c3 1918 ms FAIL. No
  MiniCheck variant passes all three on CPU. `not_contradicted` stays
  production default; both variants config-selectable via
  `grounding_model_name`; GPU/ONNX-era triggers remain in the ADR.
- **E1 parent-child expansion** (`7309327`): audit overturned the plan's
  "absent" expectation — expansion existed and was production-wired but ran
  before rerank, replaced leaf `chunk_id` with the parent's (**loose-profile
  parent = whole document ≤ 8192 chars** ⇒ production context was 1–2
  truncated whole-doc blobs with document-level citations), uncapped,
  ungated, eval-stubbed-off. Now: fuse → rerank full leaf pool → expand
  top_k (leaf identity kept; 2048-char leaf-centered parent window;
  containment fallback), `retrieval_parent_expansion=True` +
  `..._max_characters` settings; `get_parent_chunks_by_child_ids` input ids
  normalized via `_to_uuid_hex` (SQLite hex storage silently no-ops the
  lookup otherwise). **The eval gate caught the first design's regression**
  (dedupe by parent id zeroed 6 multi-span questions, recall@10 1.0 → 0.9 —
  whole-doc parents collapse all of a doc's leaves); fixed with content-true
  containment dedupe (drop a hit only if its expanded text ⊆ a kept hit's
  text — provably group-safe). Final gate: ON vs committed baseline deltas
  **+0.0000** across recall/nDCG/MRR @5/10/20; positive control 60 lookups /
  1200 parents resolved; OFF arm reproduces the committed baseline
  bit-for-bit. Id-metric movement was structurally unavailable (leaf ids
  preserved by design) — the value is leaf-precise citations, capped context
  windows, eval/production parity, correct leaf-text reranker input.

## IN FLIGHT — reranker eval arm (resume here)

**Goal**: ranking is the measured weakness (MRR@10 0.927, nDCG@10 0.944,
recall saturated at 1.000; 5 questions place first-relevant at rank 4–8) and
production runs the **stub** reranker (`reranker_backend="disabled"`).
`bge-reranker-v2-m3` is the accepted ADR-0014 model, implemented and
config-off — enabling it is the one ranking lever inside the models freeze.

**What exists (committed in the final session commit)**:
- `tests/eval/conftest.py`: third pre-built service
  `search_service_real_reranker` (BgeRerankerV2M3 + expansion ON) on the
  shared eval stack, plus `search_service_parent_expansion` (stub arm) for
  the latency A/B.
- `tests/eval/test_retrieval_reranker_arm.py`: measures quality lifts vs the
  committed baseline AND per-query latency on both arms (warmed, identical
  stack). **Decision rule frozen in the docstring + report**: flip the
  production default iff (MRR@10 or nDCG@10 lift ≥ +0.02 AND recall@10 drop
  ≤ 0.02) AND mean overhead ≤ 1000 ms/query on this hardware; any flip needs
  VPS latency re-verification before the ADR-0017 SLA margin is relied on.

**The blocker (diagnosed, not yet fixed)**: the first run failed in
FlagEmbedding's reranker:

```
AttributeError: XLMRobertaTokenizer has no attribute prepare_for_model
  (transformers/tokenization_utils_base.py:1315, via FlagReranker.compute_score)
```

Root cause confirmed: **FlagEmbedding 1.4.0's
`BaseReranker.compute_score_single_gpu` calls `tokenizer.prepare_for_model`,
which transformers 5.x removed for slow tokenizers** (installed: transformers
5.8.1). The backend suite stays green because `test_bge_reranker.py`
monkeypatches `FlagReranker` with a fake — i.e. **the real reranker path is
broken in this environment and production `reranker_backend=
"bge-reranker-v2-m3"` would crash on first rerank.** The BGE-M3 *embedder*
(BGEM3FlagModel, same package) works — the incompat is reranker-specific.

**Recommended fix** (next session, TDD): reimplement `BgeRerankerV2M3`
(`apps/api/app/services/retrieval/bge_reranker.py`) on plain transformers —
`AutoModelForSequenceClassification` + `AutoTokenizer`; bge-reranker-v2-m3 is
a standard XLM-RoBERTa cross-encoder: scores =
`model(**tokenizer(pairs, padding=True, truncation=True, max_length=512,
return_tensors="pt")).logits.squeeze(-1)`. This drops the fragile
FlagEmbedding dependency for the reranker only (house precedent: the
grounding verifier already uses plain transformers) and keeps the class
interface/config unchanged. Do NOT pin transformers < 5 — the MiniCheck
paths and the whole suite are validated on 5.8.1. Verify against the real
model with a 2–3 pair smoke test (relevance ordering sanity) before the
eval arm; weights (~2.2 GB, `BAAI/bge-reranker-v2-m3`) are now in the HF
cache from the failed run.

**Then**: `python -m pytest tests/eval/test_retrieval_reranker_arm.py -q -s`
(~5–10 min warm; keep the machine otherwise idle — it times 120 searches),
apply the frozen rule to `tests/eval/reports/retrieval_reranker_arm.json`,
flip `reranker_backend` default + note in ADR-0014 if it passes (VPS caveat),
or record the no-win. PROJECT_STATE row + TASKS.md checkbox either way.

## After that, in order

1. **Distractor corpus** (likely prerequisite for all further ranking/recall
   evals): the C5 caveat binds — the 16-doc corpus is topically distinct;
   recall is saturated and, if the reranker arm saturates nDCG/MRR too,
   nothing ranking-based can show a win either. Author near-duplicate /
   same-topic distractor fixture docs + evidence spans (C5 pattern:
   `tests/eval/fixtures/sample_corpus/` + `docs/uber-rag/eval/heldout-v1.yaml`
   evidence blocks, rot-guarded loader asserts).
2. **E2 — ADR-0020 contextual augmentation** (ADR first, docs-only): breadcrumb
   arm (no LLM) + llm arm via the existing ppq seam — both freeze-compatible.
   Technique sources to verify for the ADR: Anthropic contextual-retrieval
   post (Tier 2), Jina late-chunking arXiv:2409.04701 (Tier 1).
3. **E3 — ADR-0021 query understanding** (existing LLM seam, route-gated).
4. **E4 — reindex CLI only** (bake-offs deferred). **E5 deferred** (freeze).

## Environment & gotchas (this machine)

- Python = conda base (`/opt/homebrew/Caskroom/miniconda/base/bin/python`),
  no `.venv`. transformers **5.8.1**, FlagEmbedding **1.4.0** (see blocker).
  Weights cached: BGE-M3, NLI deberta, MiniCheck FT5-L + RoBERTa-L,
  bge-reranker-v2-m3 (~2.2 GB, from the failed run).
- `PPQ_API_KEY` is set in the shell env (real-LLM tests skip without it;
  ~60 calls ≈ 15–18 min for the grounding faithfulness suite). Never print it.
- `api.github.com` times out; `github.com` + raw.githubusercontent.com work
  (used to verify MiniCheck recipes upstream). HF hub + HF API
  (`curl https://huggingface.co/api/models/<repo>`) work — Tier-1 fallback.
- Eval reports policy: canonical JSON committed under `tests/eval/reports/`;
  `*.log` gitignored. Numbers without a committed report are not citable.
- The eval fixture's `eval_stack` is session-scoped and now exposes THREE
  services: `search_service` (baseline arm, expansion stubbed OFF — keeps the
  committed baseline reproducible), `search_service_parent_expansion`
  (E1 production shape), `search_service_real_reranker`. Per-run document
  UUIDs differ; per-question chunk ids in reports are run-specific while
  metrics are deterministic — `retrieval_baseline.json` aggregates must stay
  bit-identical when re-run (proven this session).
- Nightly eval CI (`.github/workflows/eval.yml`) runs retrieval_quality,
  negative_populated_corpus, hallucination_canaries — the new arm tests are
  on-demand only and NOT in CI (the failing reranker arm does not redden CI).
- anyio pytest plugin: real-LLM tests must pin one backend or they run twice.
- Commit style: conventional commits, trailer
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; commit per task,
  PROJECT_STATE row per task, push only when the user says "push".

## Verification commands

```bash
python -m pytest apps/api/app/tests/ -q                        # backend suite (expect 507/3 skipped)
python -m pytest tests/eval/test_retrieval_quality.py -q       # baseline arm (~35 s warm; aggregates must match committed)
python -m pytest tests/eval/test_retrieval_parent_expansion.py -q  # E1 gate (passes)
python -m pytest tests/eval/test_retrieval_reranker_arm.py -q  # BLOCKED on FlagEmbedding/transformers fix
python -m pytest tests/eval/test_hallucination_canaries.py -q  # canary guard (CPU, models cached)
```

Do not regress: retrieval baseline aggregates, ADR-0017 SLA numbers, negative
compliance 1.00, ACL leakage tests, canary catch-rate assertions, E1 unit
tests (`test_hybrid_retriever.py` — the containment-dedupe regression test
encodes the eval-gate finding).
