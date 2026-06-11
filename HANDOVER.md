# HANDOVER — resume at Phase E (written 2026-06-11)

For a fresh session continuing the master plan. Read in this order:

1. `AGENTS.md` — startup protocol (mandatory: read PROJECT_STATE.md + TASKS.md first).
2. `docs/superpowers/plans/2026-06-10-sota-master-plan.md` — **the canonical forward
   plan** (Phases A–H, executor contract at the top, per-phase completion notes
   inline). Phases A–D carry ✅ COMPLETE blocks with their evidence and bindings.
3. `docs/uber-rag/PROJECT_STATE.md` — status header + Recent-changes rows for
   everything summarized below.

## Where things stand

Master plan **Phases A–D are COMPLETE** (2026-06-10 → 2026-06-11), all pushed to
`origin/main` (HEAD `03f2b38` at handover) with CI green (SQLite suite + Postgres
migration jobs). Backend suite: **492 passed, 3 skipped** via
`python -m pytest apps/api/app/tests/ -q`.

- **A — truth & hygiene:** eval-artifact policy (canonical JSON in
  `tests/eval/reports/`, logs gitignored); P2 operability 7/7; Qdrant expiry
  enforced via numeric `expires_at_ts` (**fail-closed: pre-2026-06-10 corpora,
  incl. the VPS, return no Qdrant results until re-ingested**); docs reconciled.
- **B — sentence-incremental verified streaming (ADR-0018):** every sentence
  verified before emission; `retract`/`truncate` policy; process-wide
  verification gate (`threading.Semaphore(1)` in `chat_service.py` — concurrent
  CPU predicts thrash torch otherwise); per-request NLI model-reload fixed
  (cached factories in `routes/chat.py`). Measured: **P50 first-verified-token
  3.11s / P95 3.22s** at 5 concurrent — ADR-0017 SLA passing.
- **C — retrieval measurement rig:** span-anchored ground truth
  (`evidence: [{doc, span}]` in `docs/uber-rag/eval/heldout-v1.yaml`, resolved at
  runtime to chunk-ID equivalence groups, rot-guarded); grouped recall/MRR/nDCG;
  60 evidence-backed questions over 16 fixture docs (de=7, pt=7). Baseline
  (`tests/eval/reports/retrieval_baseline.json`): **recall@10 1.000, nDCG@10
  0.944, MRR@10 0.927; DE+PT subsets 1.000**. Nightly advisory CI gate
  (`.github/workflows/eval.yml`) compares against it (flip `ADVISORY_FLAG` to ""
  after two clean weeks — started 2026-06-11).
- **D — grounding verifier:** **ADR-0019 Rejected with data** (frozen criteria
  applied mechanically). Canary catch 1.00 (the `not_contradicted` blind spot is
  total — 10/10 fabrications pass it); faithfulness 0.578 (54/81 rejections are
  answer META-DISCOURSE, zero fabrications found in 60 production answers);
  latency 3964 ms/sentence CPU. `not_contradicted` stays production default;
  `verifier_backend="grounding"` (MiniCheck-FT5-L) stays config-selectable;
  canaries run nightly in CI; judge calibration kappa 0.563
  (`tests/eval/harness/judge.py`, eval-only).

## Phase E — what to do next, in order

Full specs in the master plan § Phase E (+ its Phase C/D binding notes). Summary:

1. **E0a — answer-style fix (START HERE; small, user-facing bug).**
   `apps/api/app/services/llm_backend.py:204` renders `rank={block.rank}` into
   prompt block headers; the LLM parrots it into user-visible answers (one
   answer contained a garbled `rank=!!!…2`). Replace with human-oriented labels
   (`[Source N: title]`), add a system-instruction rule against echoing
   labels/meta-discourse (`SYSTEM_INSTRUCTION` in the same file), update unit
   tests (`test_llm_backend.py` asserts message rendering). Afterwards,
   optionally re-run `tests/eval/test_grounding_faithfulness.py` (needs
   `PPQ_API_KEY`, ~60 LLM calls, ~18 min) — re-measuring ADR-0019 criterion 1
   is the documented reopen path; the old answers are persisted in
   `tests/eval/reports/grounding_vs_nli.json` for before/after comparison.
2. **E1 — parent-child expansion audit.** The hybrid retriever has a
   `search_sources_repository` seam consumed for parent lookup; the eval
   fixture stubs it to `{}` (`tests/eval/conftest.py`,
   `_EvalSearchSourcesRepo`). Audit whether production wiring actually expands
   leaf→parent; wire + eval-gate per plan.
3. **E2 — contextual augmentation (ADR-0020).** **Binding caveat from C5:** the
   eval corpus is topically distinct ("easy") — recall is saturated at 1.000,
   so recall-oriented upgrades cannot show a win; judge by nDCG/MRR lift or
   author distractor/near-duplicate docs first. **Ranking is the measured
   weakness** (5 questions place first-relevant at rank 4–8; the eval fixture
   is dense-only with a stub reranker — a real-reranker eval arm is the obvious
   first experiment).
4. **E3 — query understanding (ADR-0021)**, **E4 — reindex CLI + conditional
   embedder/reranker bake-offs**, **E5 — answering-LLM bake-off** (ADR-0004
   scheduled reopen; decision rule frozen in the plan: smallest servable model
   within 0.02 of incumbent quality).

Phase E entry gate (researcher pass) is REQUIRED before E2+ model/technique
adoption: re-check embedder/reranker/LLM model cards (Tier 1). Note: WebSearch
hit a session limit once; the HF model API via `curl
https://huggingface.co/api/models/<repo>` is a reliable Tier-1 fallback
(used for the Phase D gate).

## Environment & gotchas (this machine)

- Python = conda base (`/opt/homebrew/Caskroom/miniconda/base/bin/python`),
  **no `.venv`**; ML stack installed; MiniCheck + NLI + BGE-M3 weights cached.
- `PPQ_API_KEY` is set in the shell env (required by load test, D3, D5; tests
  skip without it). Never print it.
- `api.github.com` times out from this network; `github.com` works. `gh` CLI
  fails — verify CI via
  `curl -sL https://github.com/lostsock1/RAG/actions | grep -o 'aria-label="[^"]*Run [0-9]* of tests[^"]*"'`.
- anyio's pytest plugin parametrizes over asyncio AND trio — real-LLM tests
  must pin `anyio_backend` to one backend (see `tests/eval/load/test_chat_load.py`)
  or they run twice.
- Eval reports policy: canonical JSON committed in `tests/eval/reports/`;
  `*.log` gitignored. Numbers without a committed report are not citable.
- Commit style: conventional commits, trailer
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`; commit per task,
  PROJECT_STATE row per task, push only when the user says "push".

## Verification commands

```bash
python -m pytest apps/api/app/tests/ -q                      # backend suite (expect 492+/3 skipped)
python -m pytest tests/eval/test_retrieval_quality.py -q     # retrieval baseline (~35 s warm)
python -m pytest tests/eval/test_hallucination_canaries.py -q # canary guard (CPU, models cached)
python -m pytest tests/eval/load/test_chat_load.py -v        # streaming SLA (needs PPQ_API_KEY, real cost)
```

Do not regress: retrieval baseline aggregates (compare via
`python -m tests.eval.harness.cli --compare-baseline ... --candidate ...`),
ADR-0017 SLA numbers, negative compliance 1.00, ACL leakage tests, canary
catch-rate assertions.
