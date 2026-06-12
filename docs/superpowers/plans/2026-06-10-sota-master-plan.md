# Uber-RAG SOTA Master Plan — Phases A–H

Date: 2026-06-10
Author: architect session (design + direction only; implementation delegated)
Status: ACTIVE — this is the canonical forward plan. Supersedes the "Next recommended
actions" list in `PROJECT_STATE.md` (which now points here).

---

## 0. Design verdict

**The current design is APPROVED.** The architecture is sound and unusually disciplined:
swappable seams everywhere (`Parser`, `Embedder`, `Reranker`, `LlmBackend`,
`AnswerVerifier`, `WorkflowDispatcher`), ACL enforced at multiple layers with leakage
tests, truthful failure modes (503 over silent fallback), evidence discipline, and
ADR-gated decisions. Nothing in the core design needs to be torn up.

Approved with **five amendments** that move the platform to state-of-the-art. Each is a
phase below, and each respects the existing seams — no rewrites:

| # | Amendment | Why | Phase |
|---|-----------|-----|-------|
| 1 | **Sentence-incremental verified streaming** | The 2026-05-23 fix buffers the *entire* answer before emitting any token (`chat_service.py:216-246`). Evidence discipline is preserved but TTFT ≈ full-answer latency. Verify per sentence, emit per sentence. | B |
| 2 | **Grounding-specific verifier (true support metric)** | ADR-0016 honestly admits `not_contradicted` is a guardrail, not a support metric. A hallucination on an absent topic passes today. MiniCheck-class grounding models solve exactly the paraphrase problem that broke entailment mode (0.113). This is ADR-0016's own revisit trigger #1. | D |
| 3 | **Measurement before model churn** | Retrieval quality is currently unmeasured (no recall@k/nDCG; 155 of 170 heldout questions skeletal). Every SOTA retrieval claim must pass a bake-off — so build the bake-off rig first. | C |
| 4 | **Contextual chunk augmentation + query understanding** | Highest-ROI retrieval upgrades available: chunk-context prefixes at ingest (Anthropic contextual-retrieval result: ~35–49% retrieval-failure reduction) and route-gated multi-query/decomposition. Both config-gated, both eval-gated by the Phase C rig. | E |
| 5 | **Phase 4 evidence refresh first** | README and PROJECT_STATE currently disagree about Phase 4 closeout. The streaming fix invalidated the load numbers. Truth debt is paid before new features. | A |

Phase ordering: **A → B → C → D → E → F → G**, with H as an open-ended, eval-gated menu.
F (book profile + UI) is parallelizable with D/E (disjoint file trees) if two executors
are available; default is sequential.

Mapping to `ROADMAP.md`: A = Phase 4 closeout refresh + hardening tail; B–E = new
SOTA workstreams inserted before the old Phase 5; F = old Phase 5; G = old Phase 6;
H = old Phase 7. Task A3 updates `ROADMAP.md` to record this resequencing.

---

## 1. Executor contract (read before every task)

This plan is written to be executed by a mid-tier LLM, one task per session.
These rules are mandatory and override convenience:

1. **Startup**: read `docs/uber-rag/PROJECT_STATE.md`, `docs/uber-rag/TASKS.md`, and
   the section of this plan for your assigned task. Read every file you will edit
   before editing it. Do not start coding before you can state the acceptance
   criteria of your task from memory.
2. **Strict TDD**: write the failing test first, watch it fail for the *expected
   reason*, implement the smallest change, watch it pass, then run the targeted
   regression suite, then the full backend suite:
   `python -m pytest apps/api/app/tests/ -q` (expect ≥ 417 passed; live-Temporal test
   may skip). A task is not done with a red suite. Never delete, skip, or weaken an
   existing test to get green.
3. **Never weaken security**: ACL filters, leakage tests, audit writes, loopback
   dev-auth guards, and evidence-discipline checks may be extended, never relaxed.
   If your change makes an ACL test fail, your change is wrong.
4. **Truthful failure**: every config-gated capability must fail loudly
   (503 / startup error) when selected but unavailable. No silent fallbacks. This is
   an established house rule — mirror how `reranker_backend` / `llm_backend` /
   `search_backend` do it in `apps/api/app/core/config.py` and
   `apps/api/app/services/retrieval/runtime.py` / `llm_runtime.py`.
5. **Seams, not hardcoding**: new capabilities go behind a Protocol + stub
   implementation + config gate, exactly like `Reranker`/`LlmBackend`. Stub first,
   real adapter second, runtime wiring third — three separately testable slices.
6. **No fabricated numbers**: every metric you report must be the verbatim output of
   a command you ran. Save eval outputs to `tests/eval/reports/` as JSON. If you
   cannot run a measurement (missing API key, no network), say so explicitly and mark
   the task blocked — do not estimate.
7. **Memory updates**: every completed task ends with (a) a row in
   `PROJECT_STATE.md` → "Recent changes" (date, change, files, verification output),
   (b) the matching checkbox in `TASKS.md` and in this plan, (c) ADR status updates
   if the task is an ADR task.
8. **ADR tasks are docs-only** (planner role): they touch `docs/uber-rag/**` only.
   Implementation tasks follow ADR acceptance, never precede it.
9. **Stop conditions**: if a task requires a decision this plan does not cover, STOP.
   Append your question to section 11 ("Open questions") of this plan and end the
   session. Guessing at direction is the one unforgivable failure mode.
10. **Secrets**: never print, commit, or log `LLM_API_KEY`, Keycloak secrets, or
    `.env` contents.
11. **Size discipline**: tasks are sized S (≤ ~150 LOC diff), M (≤ ~400), L (≤ ~800).
    If your diff is blowing past the size, you misread the task — stop and re-read.

Verification command vocabulary used below:

```bash
# full backend suite (SQLite)
python -m pytest apps/api/app/tests/ -q
# eval harness suites (need ML extras and, where noted, LLM_API_KEY)
python -m pytest tests/eval/ -q
# load test (needs LLM_API_KEY; marked/slow)
python -m pytest tests/eval/load/test_chat_load.py -v
# frontend (Phase F)
cd apps/web && npm ci && npm run build
```

---

## 2. Current state snapshot (verified 2026-06-10)

- Phases 0–4 implemented. 417 backend tests green locally. CI: SQLite job + Postgres
  migration job (`.github/workflows/tests.yml`).
- Phase 4 was declared closed 2026-05-23, **then** commit `1ce0d30` changed
  `/chat/stream` to buffer all tokens until post-generation verification passes.
  README (commit `894c5fa`) honestly flags: load numbers stale, faithfulness wording
  needs care, docs need reconciliation. `PROJECT_STATE.md` still says "CLOSED" —
  the two disagree. Phase A fixes this.
- Uncommitted working tree: modified `tests/eval/reports/nli_both_modes.json`
  (the documented post-retriever-rewrite re-run: entailment 0.1333, not_contradicted
  per-question changes), plus untracked `tests/eval/reports/*.log` from the 05-22 runs
  and an untracked `.agents/` directory (local book-skill tooling).
- Known, documented gaps this plan closes: Qdrant payload ACL filter does not enforce
  expiry; 7 P2 operability items; book-profile chunker absent; frontend not E2E
  verified; parent-child expansion listed in the architecture invariant but no
  `expansion` module exists under `apps/api/app/services/retrieval/`; heldout eval set
  mostly skeletal; verifier is a contradiction guardrail.

---

## Phase A — Truth & hygiene: honest Phase 4 closeout + hardening tail

**Goal**: repo says one true thing about Phase 4; eval artifacts have a canonical
policy; the 7 deferred P2 items and the Qdrant expiry ACL gap are closed.
**No entry gate** (no new dependencies). All tasks are S/M.

### A1 — Eval artifact policy + commit the pending re-run (S)
- **Files**: `.gitignore`, `tests/eval/reports/`, `docs/uber-rag/adr/0016-faithfulness-metric-selection.md`
- **Do**: Adopt policy: canonical eval results are committed JSON under
  `tests/eval/reports/`; raw pytest logs are not tracked. Add
  `tests/eval/reports/*.log` to `.gitignore` and delete the three stray `.log` files.
  Commit the modified `nli_both_modes.json`. Update ADR-0016's data table to note the
  re-measured entailment value (0.133 vs originally 0.113; same conclusion). Add
  `.agents/` to `.gitignore` (local tooling, not project source).
- **Accept**: `git status` clean of eval logs; ADR-0016 mentions both measurements;
  policy sentence added to `docs/uber-rag/EVALUATION_HARNESS.md`.

### A2 — Re-run streaming load test against buffered streaming; record honestly (M)
- **Files**: `tests/eval/load/test_chat_load.py`, `tests/eval/reports/load_post_buffering.json`, `docs/uber-rag/adr/0017-streaming-latency-sla.md`
- **Do**: Make the load test emit a JSON report (P50/P95 first-token, total latency,
  error count) to `tests/eval/reports/`. Run it with the real ppq backend
  (`LLM_API_KEY` required). Expectation to record, not hide: **first token is now
  first *verified* token, so P50 first-token ≈ full answer latency and will likely
  violate ADR-0017's P50 < 5s.** Update ADR-0017 status to "Accepted — currently
  failing by design after evidence-safe buffering; remediation = ADR-0018 (Phase B)".
- **Accept**: committed JSON report with real numbers; ADR-0017 updated; no doc claims
  the old 2.5s number for the current code.

### A3 — Reconcile PROJECT_STATE / TASKS / README / ROADMAP (S)
- **Files**: `docs/uber-rag/PROJECT_STATE.md`, `docs/uber-rag/TASKS.md`, `README.md`, `docs/uber-rag/ROADMAP.md`
- **Do**: Single truthful Phase 4 statement everywhere: all four exit criteria were
  met on 2026-05-23; the subsequent evidence-safe streaming change invalidated the
  *streaming latency* number; refreshed measurement from A2 is the current number.
  Check off the four stale `[ ]` Phase 4 items in `TASKS.md` (they were completed —
  see PROJECT_STATE 2026-05-23 rows) and the duplicated Phase 6 eval items that are
  already done. Add this plan's phases to `ROADMAP.md` as the active sequencing.
- **Accept**: grep for "refresh needed" / contradictory closeout claims returns
  nothing; TASKS.md reflects reality.

### A4 — Close P2-1 … P2-7 operability items (M)
- **Files/spec**: exactly as itemized in `docs/uber-rag/TASKS.md` lines 106–114 and
  `docs/superpowers/plans/2026-05-23-phase-1-2-audit-and-fixes.md` § P2.
- **Do**: one commit per item, TDD each: (1) OpenSearch indexer honors
  `opensearch_verify_certs`/`opensearch_use_ssl`; (2) `reset_dependency_caches()`
  conftest helper; (3) dedup IntegrityError 3-attempt retry; (4) narrow startup
  recovery exception swallow to SQLAlchemy operational errors; (5) Temporal client
  cached across dispatches + closed in lifespan; (6) `isinstance`-based Temporal
  client detection; (7) fail-fast on Docling-without-storage misconfig.
- **Accept**: 7 checkboxes flipped in TASKS.md; full suite green.

### A5 — Qdrant expiry enforcement via numeric payload (M)
- **Files**: `apps/api/app/services/indexers/qdrant_indexer.py`,
  `apps/api/app/services/retrieval/acl_filter.py`,
  `apps/api/app/services/retrieval/qdrant_retriever.py`, tests, migration note in
  `docs/uber-rag/SECURITY_ACL.md`
- **Do**: Index a numeric `expires_at_ts` (Unix epoch seconds; use a sentinel of
  `0`/absent for "no expiry" — decide in code comments, prefer *omitting the key* and
  using a `should`-clause of `[expires_at_ts missing, expires_at_ts > now]`). Restore
  the expiry clause in the Qdrant ACL filter using `Range` on the numeric field —
  this avoids the JSON-null matching problem that forced the 2026-05-23 removal.
  Leakage test: an expired grant's chunk must not return from Qdrant retrieval even
  when SQL filtering is bypassed.
- **Accept**: new leakage test red→green; existing ACL tests untouched and green;
  `SECURITY_ACL.md` enforcement-layers table updated. Note: existing collections need
  reindex for the new payload field — document this in the migration note (reindex
  tooling arrives in E4; until then dev/test corpora are small enough to re-ingest).

**Phase A exit criteria**: working tree clean; docs agree; load number for current
code committed; P2 0/7 → 7/7; Qdrant expiry leakage test green.

**✅ PHASE A COMPLETE — 2026-06-10.** A1 `1ebec84`; A2 `c3de521` (canonical:
P50 5.97s / P95 10.75s, SLA FAIL by design, ADR-0017 updated); A4 `7a8204c`..`935138e`
(7/7, suite 435); A5 `1d57e06` (fail-closed `expires_at_ts`, suite 440, real-stack
eval fixture verified); A3 doc reconciliation in the closing commit. Final suite:
**440 passed, 3 skipped.** Note for B3: A2's methodology pinned the load test to one
anyio backend; keep that. Note for E4/deploys: pre-A5 Qdrant corpora (VPS) need
re-ingest before retrieval returns results there.

---

## Phase B — Streaming that actually streams (ADR-0018)

**Goal**: restore time-to-first-token to seconds while *strengthening* evidence
discipline: no token is ever emitted before its sentence is verified.
**Entry gate**: none external — this is internal architecture. ADR-0018 is the gate.

### B1 — ADR-0018: sentence-incremental verified streaming (ADR task, planner) (M)
- **Files**: `docs/uber-rag/adr/0018-incremental-verified-streaming.md`, `docs/uber-rag/ARCHITECTURE_DECISIONS.md`
- **Design to record** (this is the decision, executor writes it up):
  - Pipeline: LLM token stream → **sentence assembler** (reuse the verifier's existing
    sentence-splitting logic from `apps/api/app/services/answer_verifier*.py` so
    assembly and verification agree on boundaries) → per-sentence verification against
    the already-built context blocks → emit that sentence's tokens only on pass.
  - **Pipelining**: verify sentence *N* concurrently while the LLM streams sentence
    *N+1* (asyncio task + ordered emission queue), so verification latency hides
    behind generation. NLI on (1 sentence × ≤ max_blocks) pairs is tens of ms on CPU.
  - **Failure policy** (config `stream_verification_policy`, default `retract`):
    - `retract`: on first unsupported sentence, emit
      `{"type":"retraction","data":{"reason":"verification_failed"}}` then
      `final(status=not_enough_evidence)` with the standard message. Clients must
      replace displayed partial text. Honest UX: partial text was *verified* text,
      but a truncated argument can mislead, so default is full retraction.
    - `truncate`: stop at the last verified sentence, emit
      `final(status=answered, truncated=true)`. Off by default; exists for UX
      experiments.
  - Blocking `/chat` is unchanged (it already verifies whole answers post-hoc).
  - SSE event grammar change: `verification` becomes per-sentence-batch optional;
    `retraction` event added; `final` gains optional `truncated`. Document the full
    grammar in `API_CONTRACT.md` + `docs/uber-rag/api/openapi.yaml`.
  - Why this is the right trade: evidence-discipline invariant #5 preserved verbatim
    (nothing unverified is ever rendered), ADR-0008's fast-hot-path restored, and the
    happy path (measured: 15/15 answers pass not_contradicted today) streams at
    near-raw-LLM latency. This is differentiating: stock RAG stacks stream unverified
    text; we stream verified text at comparable latency.
- **Accept**: ADR Accepted; event grammar table present; failure-policy semantics
  unambiguous (a mid-tier executor implements B2 from the ADR alone).

### B2 — Implement sentence assembler + incremental verifier orchestration (L)
- **Files**: `apps/api/app/services/chat_service.py` (`answer_stream`),
  new `apps/api/app/services/streaming_verifier.py` (assembler + ordered pipeline),
  `apps/api/app/core/config.py` (`stream_verification_policy: Literal["retract","truncate"] = "retract"`),
  `apps/api/app/tests/unit/test_streaming_verifier.py`,
  `apps/api/app/tests/integration/test_chat_stream.py`
- **Do** (TDD order):
  1. Unit-test the assembler: token fragments → sentences, consistent with the
     verifier's splitter; handles abbreviations/decimals at least as well as the
     existing splitter (do not invent a smarter splitter; *reuse*).
  2. Unit-test ordered pipelining with a fake verifier (slow verify must not reorder
     emission; sentence N+1 never emits before N).
  3. Integration: with a scripted stub LLM stream, assert (a) first `token` event is
     emitted *before* the stub finishes the full answer (this is the TTFT regression
     test — it fails against today's buffer-everything implementation), (b) an
     unsupported sentence triggers `retraction` + `not_enough_evidence` and no
     post-failure tokens, (c) `truncate` mode behavior, (d) the existing 12
     stream tests still pass (update any that asserted the old all-at-once order —
     that contract is superseded by ADR-0018, the *evidence-safety* assertions must
     remain).
- **Accept**: TTFT regression test green; no test asserting "unverified text never
  emitted" was weakened; full suite green.

### B3 — Contract docs + load re-measurement (S)
- **Files**: `docs/uber-rag/API_CONTRACT.md`, `docs/uber-rag/api/openapi.yaml`,
  `tests/eval/reports/load_incremental_streaming.json`, `docs/uber-rag/adr/0017-streaming-latency-sla.md`
- **Do**: document the new SSE grammar; re-run the A2 load test; record P50/P95
  first-verified-token. Expectation: back near the pre-fix ~2.5s (LLM-bound).
  Update ADR-0017 from "failing by design" to measured-pass/fail against
  P50 < 5s / P95 < 10s.
- **Accept**: committed report; ADR-0017 reflects measured state.

**Phase B exit criteria**: P50 first-verified-token < 5s at 5 concurrent (ADR-0017),
with the buffered-everything path gone and evidence-safety tests intact.

**✅ PHASE B COMPLETE — 2026-06-10.** B1 `b0aefb8` (ADR-0018 Accepted; amended
pipelining → inline-v1); B2 `d777e54` (assembler + incremental verify in worker
thread + retract/truncate + per-request NLI model-reload fix; suite 458); B3 in the
closing commit. Measurement story: ungated incremental was *worse* than buffered
(P50 8.0s — concurrent per-sentence predicts thrash torch's intra-op threads);
process-wide verification gate fixed it. **Final: P50 3107ms / P95 3221ms
first-verified-token, totals 5.2s/7.7s, SLA PASSING, load test green.** Notes for
later phases: (1) Phase D's grounding verifier must keep the verification-gate
pattern (any CPU cross-encoder thrashes the same way); (2) the ADR-0008 ~2s gap is
now purely provider TTFS — Phase G local serving is the lever; (3) the SSE grammar
in API_CONTRACT.md is the contract for Phase F's chat UI (retraction handling
required).

---

## Phase C — Retrieval measurement foundation

**Goal**: retrieval quality becomes a number we can regress on. Every later
retrieval/model change (D, E, H) is accepted or rejected by this rig.
**Entry gate** (researcher, 1 short note): confirm current best practice for graded
relevance labeling with LLM assistance (LLM labels + human spot-check); nothing else
new is being adopted.

### C1 — Ground-truth schema + backfill the answerable subset (M)
- **Files**: `docs/uber-rag/eval/heldout-v1.yaml`, `tests/eval/harness/loader.py`, loader tests
- **Do**: extend the question schema with `expected_chunk_ids: []` (deterministic
  uuid5 chunk ids from the fixture corpus) and optional `expected_doc_ids`,
  `answer_span` (verbatim source sentence). Backfill the 15 fixture-corpus questions
  exactly (ground truth is known). Loader validates the new fields; absent fields
  remain legal (skeletal questions stay loadable).
- **Accept**: loader tests green; 15 questions carry chunk-level ground truth.

### C2 — Retrieval metrics in the scorer: recall@k, MRR, nDCG@k (M)
- **Files**: `tests/eval/harness/scorer.py`, `tests/eval/harness/reporter.py`, unit tests
- **Do**: implement recall@{5,10,20}, MRR@10, nDCG@10 against `expected_chunk_ids`
  (binary relevance now; the scorer API takes graded gains for later). Hand-computed
  tiny fixtures in tests (e.g., 3 hits, known ideal ordering → known nDCG).
- **Accept**: unit tests with hand-verified values green.

### C3 — Retrieval-only runner mode (no LLM) (M)
- **Files**: `tests/eval/harness/runner.py`, `tests/eval/harness/cli.py`, `tests/eval/test_retrieval_quality.py`
- **Do**: `--mode retrieval` runs query → hybrid retrieval (+ reranker when
  configured) → score against ground truth, skipping generation/verification. Uses
  the existing session-scoped `eval_stack` fixture (`tests/eval/conftest.py`). Emits
  `tests/eval/reports/retrieval_baseline.json`. Run it; commit the baseline.
- **Accept**: baseline JSON committed with real numbers on the 15-question subset;
  runtime < 5 min on CPU (BGE-M3 already loads in the fixture).

### C4 — CI eval gate: advisory, then enforcing (M)
- **Files**: `.github/workflows/tests.yml` (new job), `tests/eval/harness/cli.py` (`--compare-baseline`)
- **Do**: nightly/manual-dispatch CI job (not per-PR — BGE-M3 download is heavy):
  run retrieval-only eval + negative-compliance (stub-LLM path), compare to committed
  baselines, post a summary. Two-stage rollout: `advisory` (report only) now; flip to
  `enforcing` (fail on regression) after two clean weeks. Thresholds: recall@10 drop
  > 0.02 absolute → fail; negative-answer compliance < 1.0 → fail; faithfulness
  (when LLM key present) drop > 0.05 → fail.
- **Accept**: CI job runs green in advisory mode with artifacts uploaded.

### C5 — Heldout backfill at scale + multilingual subset (L, parallelizable)
- **Files**: `docs/uber-rag/eval/heldout-v1.yaml`, `tests/eval/fixtures/`, a backfill helper under `tests/eval/harness/`
- **Do**: grow the *usable* eval set from 15 to ≥ 60 questions: ingest 10–15 more
  fixture documents (include ≥ 2 German, ≥ 2 Portuguese to activate the multilingual
  subset), then semi-automatic labeling: retrieve top-20 per question, LLM-judge
  candidate relevance, human-format spot-check file committed alongside. Run the
  multilingual subset; record per-language recall (BGE-M3 is multilingual — measure,
  don't assume).
- **Accept**: ≥ 60 questions with chunk-level ground truth; multilingual numbers in a
  committed report; remaining skeletal questions explicitly counted in the report.

**Phase C exit criteria**: committed retrieval baseline on ≥ 60 questions; CI
advisory gate live; the sentence "retrieval quality is unmeasured" is dead.

**✅ PHASE C COMPLETE — 2026-06-11** (`838a141`..`bf236ca`). C0–C4 built the rig;
C5 scaled the corpus to 16 docs / 60 evidence-backed questions (de=7, pt=7).
Final baseline (`tests/eval/reports/retrieval_baseline.json`, BGE-M3 dense, stub
reranker, lexical off): **recall@10 1.000, nDCG@10 0.944, MRR@10 0.927; DE+PT
both 1.000**. Notes that bind D/E:
1. Ground truth is span-anchored — `evidence: [{doc, span}]`, runtime-resolved
   to chunk-ID equivalence groups via `tests/eval/harness/ground_truth.py`;
   zero-match raises (rot guard). Metrics are grouped per-span
   (`grouped_*_at_k` in `scorer.py`); naive chunk-level variants exist but
   penalize leaf/parent duplication — use the grouped ones.
2. **Ranking, not recall, is the measured weakness** (recall saturated at 1.000;
   5 questions place first-relevant beyond rank 3). D/E should add real-reranker
   and hybrid-lexical eval arms and measure the ranking lift.
3. **The corpus is "easy"** — topically distinct docs, so recall has no headroom.
   **E2 contextual augmentation is recall-oriented and CANNOT show a win on this
   corpus**; either add distractor/near-duplicate docs first (a small eval-corpus
   task) or evaluate E2 on nDCG/MRR ranking lift, not recall. Logged in the entry
   note. **[RESOLVED 2026-06-11 — distractor corpus landed; see the Phase E
   reranker block below. New baseline MRR@10 0.834 / nDCG@10 0.875; recall
   still 1.000, so judge E2 on ranking lift.]**
4. Multilingual *retrieval* is de-risked (DE/PT 1.000); multilingual *generation*
   is still open (D/E5).
5. CI gate (`.github/workflows/eval.yml`) is advisory; flip `ADVISORY_FLAG` to ""
   after two clean weeks. The committed baseline is now the 60-question one.
6. 110 heldout questions remain skeletal — they target corpora (contracts,
   reports, emails, version-history) that do not exist as fixtures yet; backfill
   when those corpora are authored, not before.

---

## Phase D — Verifier upgrade: from contradiction guardrail to true support metric

**Goal**: faithfulness becomes a real grounding/support metric with paraphrase
tolerance, closing ADR-0016's acknowledged weakness. Production flips only on
measured wins.
**Entry gate** (researcher, mandatory before D1 acceptance): verify on Hugging Face
model cards (Tier 1) the current grounding-verifier candidates, their **licenses**
(critical — this is a commercial platform), sizes, and claimed LLM-AggreFact-class
benchmark results. Candidate list to verify, not to trust from this plan:
  - `lytang/MiniCheck-Flan-T5-Large` (~0.8B, CPU-viable; MiniCheck paper, EMNLP 2024)
  - `bespokelabs/Bespoke-MiniCheck-7B` (stronger; **license historically
    non-commercial — check**; GPU/API only)
  - IBM `granite-guardian-3.x` groundedness mode (Apache-2.0, commercially safe)
  - Vectara `HHEM-2.x` hallucination eval model
  - Any newer grounding-NLI model surfaced via Awesome-AI-Memory scan
Record findings in `docs/uber-rag/research/2026-XX-XX-phase-d-entry.md` +
`STACK_REFERENCES.md`.

### D1 — ADR-0019: grounding verifier selection (ADR task, planner) (M)
- **Files**: `docs/uber-rag/adr/0019-grounding-verifier.md`, revise `0016`'s status note
- **Do**: pick the default grounding model from the entry-gate evidence under these
  constraints: CPU-inference viable (no local GPU), commercially usable license,
  sentence×evidence scoring interface. Decision shape: new
  `verifier_backend: "grounding"` mode alongside `substring`/`nli`; scoring semantics
  = P(grounded) per sentence against best context block; keep `not_contradicted` NLI
  as the fallback config. Define the promotion criterion *in the ADR before
  measuring*: grounding-mode faithfulness ≥ 0.85 on the answered subset **and** the
  D4 canary suite catches ≥ 80% of fabrications that `not_contradicted` passes.
- **Accept**: ADR Accepted with license evidence cited; promotion criterion frozen.

### D2 — Implement `GroundingAnswerVerifier` behind the existing seam (M)
- **Files**: new `apps/api/app/services/answer_verifier_grounding.py`,
  `apps/api/app/core/config.py` (backend literal + model name + threshold settings),
  runtime wiring where `verifier_backend` is resolved, unit tests mirroring
  `test_answer_verifier_nli.py` (lazy model load, deterministic stub for tests,
  paraphrase fixture must pass, contradiction fixture must fail)
- **Do**: same adapter pattern as `NliAnswerVerifier` (lazy load, batch pairs,
  threshold + `unsupported_ratio` reuse). Truthful failure when selected but model
  unavailable.
- **Accept**: unit tests green including a paraphrase case that strict-entailment NLI
  fails today; full suite green.

### D3 — Measure both verifiers on the eval set; flip default on a win (M)
- **Files**: `tests/eval/test_grounding_faithfulness.py`, report JSON, ADR-0016/0019 updates
- **Do**: run grounding mode vs not_contradicted on the Phase C eval set (≥ 60
  questions). Apply the D1 promotion criterion mechanically. On pass: flip
  `Settings.verifier_backend` default, update ADR-0016 (Superseded-in-part) and
  ADR-0019 (Accepted-measured). On fail: record numbers, keep not_contradicted,
  ADR-0019 → Rejected with data. Either outcome is a success — that's the point of
  the rig.
- **Accept**: committed comparison report; ADR statuses match the data.

### D4 — Hallucination canary suite (S)
- **Files**: `tests/eval/test_hallucination_canaries.py`, canary fixtures
- **Do**: build ~10 canaries for the documented `not_contradicted` blind spot:
  questions whose true answer is *absent* from the corpus, paired with plausible
  fabricated answers injected through a scripted stub LLM. Assert verifier verdicts.
  This suite is the permanent regression net for verifier changes and runs CPU-only
  in CI.
- **Accept**: canaries red under `not_contradicted` where expected (documenting the
  blind spot), and the suite is wired into the C4 CI job.

### D5 — LLM-as-judge calibration mode, eval-only (M)
- **Files**: `tests/eval/harness/` judge module, report
- **Do**: harness-only (never production) LLM-judge: per answer sentence, ask the ppq
  LLM "supported by this evidence? yes/no + quote". Compute agreement (Cohen's kappa)
  between judge and the production verifier on the answered subset. This calibrates
  how much to trust the cheap verifier and becomes the standing method for auditing
  future verifier swaps.
- **Accept**: kappa reported in a committed JSON; method documented in
  `EVALUATION_HARNESS.md`.

**Phase D exit criteria**: a support-metric verifier measured against the guardrail
with frozen criteria; canary suite in CI; production default decided by data.

**✅ PHASE D COMPLETE — 2026-06-11** (`8acffc7`..closing commit). Outcome:
**ADR-0019 Rejected with data** — exactly the "either outcome is a success of the
rig" branch. Criteria applied mechanically: c2 PASS (canary catch 1.00; the
`not_contradicted` blind spot is total — 10/10 plausible fabrications pass it),
c1 FAIL (0.578 vs ≥ 0.85), c3 FAIL (3964 ms vs ≤ 500 ms). Judge calibration:
kappa 0.563/91 pairs; disagreements concentrate on the two known artifacts.
`not_contradicted` stays production default; the grounding backend is merged and
config-selectable; canaries run nightly in CI as the standing blind-spot guard.

**Bindings for Phase E (do these early):**
1. **E0a — answer-style fix (NEW, small, high-value):** `llm_backend.py:204`
   renders `rank={block.rank}` into prompt block headers; the LLM parrots it
   into user-visible answers (incl. a garbled `rank=!!!…2` artifact). Replace
   with human-oriented source labels (`[Source N: title]`), add a
   system-instruction rule against echoing labels/meta-discourse, update the
   affected unit tests. This is a user-facing quality bug independent of any
   verifier — and the **primary ADR-0019 reopen path**: re-run the D3
   measurement (c1) after it lands. Optional c3 path if c1 then passes:
   measure MiniCheck-RoBERTa-Large latency.
   **✅ E0a DONE 2026-06-11**: `_render_user_message` now emits
   `[Source N: title — heading path, page(s)]` + raw text (machine keys
   `rank=`/`citation_id=`/`chunk_id=`/`heading_path=`/`page_*=`/`text=`
   removed — citations are verifier-attached, never parsed from answers);
   `SYSTEM_INSTRUCTION` gains an anti-parroting/meta-discourse rule scoped
   to answered questions. TDD: 3 red on old rendering → 7/7 targeted →
   suite 494 passed, 3 skipped. c1 re-measurement queued next.
   **✅ c1 RE-MEASURED 2026-06-11 — PASSES post-E0a**: grounding
   faithfulness **0.578 → 0.9007** (bar ≥ 0.85), accept@ratio-0.0
   0.3667 → 0.85, 60/60 answered, NLI reference 1.0. Meta-discourse
   rejection class eliminated; 9 residual rejections are inference
   strictness / residual narration / cross-block synthesis, no substantive
   fabrication. c3 still fails (4553 ms/sentence CPU) — ADR-0019 rejection
   now stands on c3 alone; the optional c3 path (MiniCheck-RoBERTa-Large,
   offline c1+c2+c3, zero LLM calls) is open. Report committed; before-run
   at git HEAD~1.
   **✅ c3 PATH EXECUTED 2026-06-11 — REJECTION CONFIRMED**: RoBERTa-L
   offline on identical persisted answers: c1 0.7632 FAIL / c2 1.00 PASS /
   c3 1918 ms FAIL (2.4× faster than FT5-L, ~3.8× over budget). No MiniCheck
   variant passes all three on CPU. Classification recipe path merged +
   config-selectable (`grounding_model_name`) for GPU/ONNX-era reopen.
   `not_contradicted` stays; ADR-0019 reopen paths exhausted for Phase E —
   proceed to E1.
2. The D3/D5 reports persist generated answers — reuse them for any
   answer-style before/after comparison.
3. C5's "easy corpus" caveat is **RESOLVED (2026-06-11)** — distractor docs
   landed; the new baseline (MRR@10 0.834 / nDCG@10 0.875, recall@10 1.000)
   has ranking headroom. Judge E2 by nDCG/MRR lift, not recall.

---

## Phase E — Retrieval quality upgrades (each one eval-gated by Phase C)

**Goal**: measurable retrieval gains, cheapest-first. Every task here ends with a
before/after run of the C3 rig; a change that doesn't move the numbers gets reverted
or left config-off — record either way.
**Entry gate** (researcher): re-check BAAI/embedding/reranker landscape (ADR-0013/0014
revisit triggers), confirm contextual-retrieval and late-chunking sources
(Anthropic engineering post + cookbook = Tier 2; Jina late-chunking paper
arXiv:2409.04701 = Tier 1), and current Qwen3-Embedding / Qwen3-Reranker model cards
(Apache-2.0 expected — verify). **Also survey the answering-LLM landscape for E5**
(ADR-0004 reopen): current open-weight grounded-QA candidates in the ~20–120B
class, verified against current model cards (Tier 1) for license (Apache-2.0
preferred over Llama-license), multilingual coverage (German + Portuguese
required), ppq.ai/OpenAI-compat availability, and local-serving footprint
(GPU memory at int8/awq, expected TTFS). Candidate seeds to verify, not trust
(architect's list is from a Jan-2026 cutoff and is stale by definition):
Qwen3 32B-class, OpenAI gpt-oss MoE, Gemma 3 27B, Mistral Small 3.x, plus the
incumbent Llama 3.3 70B and Hermes fallback as baselines.

**DESCOPED 2026-06-11 (user directive — models frozen):** stay with current
models (BGE-M3, bge-reranker-v2-m3, ppq Llama 3.3 70B; MiniCheck variants
config-only); the platform lives on the CPU-only VPS with API-based
generation — no GPU. Consequences: the entry gate's model-survey portion,
E4's conditional embedder/reranker bake-offs, and E5's answering-LLM bake-off
are **deferred** (not cancelled — they reactivate when the freeze lifts).
E2/E3 proceed on technique merits using existing seams; technique sources
(contextual retrieval, late chunking) remain in scope for the E2 ADR. The
one ranking lever inside the freeze is enabling the already-accepted
ADR-0014 reranker (config-off today) — measured as the
`retrieval_reranker_arm` eval (frozen decision rule in
`tests/eval/test_retrieval_reranker_arm.py`); latency bars are CPU bars,
re-verified on the VPS before SLA-relevant flips ship.

**✅ RERANKER ARM MEASURED — 2026-06-11: NO FLIP.** Prerequisite fix landed
first: `BgeRerankerV2M3` reimplemented on plain transformers
(`AutoModelForSequenceClassification`, official model-card scoring) because
FlagEmbedding 1.4.0's reranker calls `tokenizer.prepare_for_model`, removed
in transformers 5.x — the real path crashed on first rerank while unit
tests stayed green on a monkeypatched fake (FlagEmbedding-free regression
guard added; real-model smoke sane; suite **511 passed, 3 skipped**).
Frozen rule applied to `tests/eval/reports/retrieval_reranker_arm.json`:
quality MRR@10 +0.0132 / nDCG@10 +0.0109 — net positive (two rank-4
questions fixed to rank 1, two perfect ones dropped to rank 2) but below
the +0.02 bar on the topically-distinct C5 corpus; latency mean overhead
**2436 ms/query** (157 → 2593 ms, P95 4084 ms) vs the 1000 ms bar on
optimistic dev-Mac CPU — fails independently of corpus difficulty.
**`reranker_backend` default stays `disabled`.** Reopen paths recorded in
ADR-0014: distractor corpus for the quality side; ONNX CPU serving (~5×
per the ADR's DeepEye note) and/or a smaller rerank candidate pool for the
latency side (same model — freeze-compatible, unscheduled). Next in line:
the distractor corpus, which gates every further ranking/recall eval.

**✅ DISTRACTOR CORPUS LANDED — 2026-06-11: C5 "easy corpus" caveat
resolved, and it changed the reranker verdict.** 8 same-topic hard-negative
docs (EN×6, DE, PT) added under `tests/eval/fixtures/sample_corpus/`: each
section echoes a target query's exact subject phrase but states a sibling
fact (a neighbouring constant/definition/element) and contains **no
evidence span** — verified programmatically across all 60 spans (a
distractor that contained a span would silently join its relevance group).
First attempt used sibling *terms* (deflation vs inflation); BGE-M3
distinguished them and MRR moved only −0.002. Rewritten to echo exact query
phrasing → baseline **MRR@10 0.927→0.834, nDCG@10 0.944→0.875** (recall@10
holds at 1.000: confusables push true evidence down a few ranks, not past
k — the intended ranking headroom, since ranking was always the measured
weakness). **Re-running the reranker arm against this harder baseline
flipped its quality verdict**: MRR@10 +0.0413, nDCG@10 +0.0314 (both clear
the +0.02 bar; recall intact) → `quality_pass=true`, recovering ~half the
introduced headroom. So the easy-corpus "+0.013, not worth it" result was a
saturation artifact; the reranker's quality value is real on a non-trivial
corpus and only CPU latency (2222 ms overhead) blocks the flip — ADR-0014's
reopen now rests on the latency path alone. E2/E3 are judgeable on ranking
lift against this new baseline.

### E1 — Parent-child expansion: audit and wire (M)
- **Files**: `apps/api/app/services/retrieval/hybrid_retriever.py`, possibly new
  `expansion.py`, `apps/api/app/repositories/chunks.py`, tests
- **Do**: Architecture invariant #3 promises parent-child expansion; the chunker
  persists a 2-level hierarchy; **no expansion module exists in retrieval**. Audit
  first: confirm whether leaf hits are expanded to parent context anywhere between
  fusion and context build. If absent (expected): after rerank, replace/augment leaf
  hit text with its parent chunk's text (dedupe when multiple leaves share a parent;
  keep leaf `chunk_id` for citations; cap expanded characters). Config-gate
  `retrieval_parent_expansion: bool = True` only after the eval gate passes.
- **Accept**: C3 before/after committed; expansion preserves citation `chunk_id`
  stability (existing citation tests green).

**✅ E1 COMPLETE — 2026-06-11.** Audit overturned the "absent" expectation:
expansion existed and was production-wired (`runtime.py` →
`get_parent_chunks_by_child_ids`) but ran BEFORE rerank, replaced the leaf
`chunk_id` with the parent's (loose profile: parent = whole document ≤ 8192
chars ⇒ production context was 1–2 truncated whole-doc blobs with
document-level citations), was uncapped, ungated, and stubbed off in the
eval fixture (committed baseline measured a pipeline production never ran).
Conformed to spec: fuse → rerank full leaf-text pool → expand top_k (leaf
identity + citation `chunk_id` kept; parent text in a 2048-char window
centered on the leaf; fallback to leaf when the truncated parent lost it);
`retrieval_parent_expansion`/`..._max_characters` settings wired
(default ON); repo lookup id-normalization fixed (`_to_uuid_hex` — SQLite
hex storage made the eval arm a silent no-op otherwise). **The eval gate
caught a real regression in the first design**: dedupe keyed on parent id
collapsed every leaf of a doc into one hit (recall@10 1.000 → 0.900, 6
multi-span questions zeroed) — replaced with content-true containment
dedupe (drop a hit only if its expanded text is inside a kept hit's text;
provably group-safe). Final gate: ON vs committed baseline **all deltas
+0.0000** (recall/nDCG/MRR @5/10/20), positive control 60 lookups / 1200
parents resolved, OFF arm reproduces the committed baseline bit-for-bit,
citation tests green. Reports: `tests/eval/reports/retrieval_parent_expansion.json`.
Suite **507 passed, 3 skipped**. Reading: the id-metric win was never
available here (leaf ids preserved by design); the change is a production
answer-path fix (leaf-precise citations + capped windows instead of
whole-doc blobs) + eval/production parity + correct reranker input for the
E2 real-reranker arm.

### E2 — ADR-0020 + contextual chunk augmentation stage (L)

**✅ E2 COMPLETE — 2026-06-11. ADR-0020 Accepted with data: NO WIN, default
stays `disabled`.** Rule frozen and committed before measurement (the
"≥ +0.03 recall@10" margin below was voided — recall@10 saturated at 1.000
post-distractor; judged on ranking lift instead: MRR@10 or nDCG@10 ≥ +0.02,
recall@10 drop ≤ 0.02, ingest cost acknowledged, breadcrumb wins ties).
Foundation + 30 TDD tests + Settings wiring (in-process AND Temporal,
truthful llm-creds failure) landed; suite 549 passed / 3 skipped; disabled
path bit-identical (7 stages pinned). Bake-off on isolated re-ingested
stacks, positive control 313/313 leaves prefixed both arms:
**breadcrumb MRR@10 +0.0090 / nDCG@10 +0.0065** (sub-bar; ~56 s ingest);
**llm MRR@10 −0.0867 / nDCG@10 −0.0686 / recall@10 −0.0167** (actively
harmful: topic-level situating context pulls same-topic confusables closer
— exactly the C5 distractor structure; 1428 s = 4.56 s/leaf ppq serial).
Report: `tests/eval/reports/retrieval_contextual_augmentation.json`.
Caveats → ADR-0020 reopen triggers: dense-only rig (contextual-BM25 share
unmeasured), short-doc corpus (book-profile heading hierarchies untested),
prompt-caching cost collapse, E3 baseline shift. Both arms stay merged and
config-selectable.

- **Files**: `docs/uber-rag/adr/0020-contextual-chunk-augmentation.md`,
  `apps/api/app/workflows/stages.py` (+ `pipeline_runner.py`) new optional
  `contextualize` stage between `chunk` and `embed`, chunk schema/model gains
  `context_prefix: str | None`, both indexers index `context_prefix + "\n" + text`
  while the API returns original `text` for display/citation, config
  `contextual_augmentation: Literal["disabled","breadcrumb","llm"] = "disabled"`, tests
- **Do**: two arms, bake off both against baseline on the C3 rig:
  - **breadcrumb** (no LLM, near-free): prefix = document title + heading path
    (already on chunks) + page anchor. Often captures much of the gain for
    structured docs.
  - **llm**: 50–100-token chunk-situating context generated per chunk at ingest via
    the existing `LlmBackend` seam (1 call/chunk; idempotent — persisted with the
    chunk; cost note in ADR; air-gap-compatible later since any local LLM can serve
    it).
  Embedding/BM25 input changes ⇒ affected corpora must re-ingest; fine for eval
  fixtures, and E4 delivers reindex tooling for real corpora.
- **Accept**: ADR Accepted with the bake-off table (baseline vs breadcrumb vs llm,
  recall@10/nDCG@10); default set to the winner **only if** it beats baseline by the
  ADR's pre-frozen margin (suggest ≥ +0.03 recall@10); pipeline tests cover the
  disabled path bit-for-bit identical to today.

### E3 — ADR-0021 + query understanding: multi-query + decomposition (L)

**✅ E3 COMPLETE — 2026-06-12. ADR-0021 Accepted with data: NO WIN (all
three arms), default stays `disabled`.** Rule frozen and committed before
measurement (MRR@10 or nDCG@10 lift ≥ +0.02, recall@10 drop ≤ 0.02, added
gated-route P50 ≤ 700 ms; subset wins record-only; cheaper passing arm
wins ties; decompose zero-trigger = not_exercised ≠ no_win). Seams +
26 unit tests + Settings wiring (truthful startup failure for LLM-backed
modes without `llm_*` creds; decompose needs none) landed first; suite
**580 passed / 3 skipped**; understander=None path byte-identical;
exact/quoted routes never consult the understander. Bake-off on the
session eval stack (no re-ingestion — query understanding changes nothing
at ingest) with paired no-understander control; rig equivalence verified
per-question. **multi_query: ranking dead flat (MRR@10 −0.0012 / nDCG@10
−0.0008) at +3030 ms added P50 (4.3× the bar)** — a clean technique
negative, not a no-op: positive control proved 60/60 paraphrase calls
(3.0/question) and 60/60 result sets perturbed; recall@10 is saturated at
1.000 so the vocabulary-mismatch headroom doesn't exist, and
topic-preserving paraphrases retrieve the same C5 confusables.
**decompose: 1/60 trigger (0/5 multi_hop questions matched — heldout
trigger-shape TODO); the lone firing fully fixed h49 (MRR@10 0.5→1.0) =
the entire +0.0084 aggregate** — subset-honesty clause: reopen evidence,
not a pass. **both: +2735 ms AND lost decompose's h49 fix to RRF
paraphrase dilution** (chapter_synthesis 0.8333 vs decompose's 1.0).
Report: `tests/eval/reports/retrieval_query_understanding.json`. All
arms stay merged + config-selectable; reopen paths in ADR-0021 (local
low-latency serving for multi_query; multi-hop heldout additions for
decompose — now with positive per-trigger evidence; E2-reopen rig
upgrades; baseline shift).

- **Files**: `docs/uber-rag/adr/0021-query-understanding.md`,
  `apps/api/app/services/retrieval/query_understanding.py`,
  `router.py` (route signal), `hybrid_retriever.py` (merge), config gates, tests
- **Do**: route-gated (never on exact/quoted routes; ADR-0008 latency budget — one
  extra LLM call only on routes that already pay for generation):
  - **multi-query**: N=3 paraphrases via `LlmBackend`, parallel retrieval, RRF-merge
    into the existing fusion (reuse `fusion.py`), then rerank as usual.
  - **decomposition**: heuristic multi-hop detection (e.g., comparative/two-entity
    questions) → sub-queries → merged evidence pool.
  Config `query_understanding: Literal["disabled","multi_query","decompose","both"] = "disabled"`.
  Deterministic stub paraphraser for tests.
- **Accept**: eval-gated like E2 (multi-hop/needle subsets are where wins should
  show); P50 search latency increase ≤ 700 ms on gated routes, measured and recorded;
  truthful 503 if enabled without an LLM backend.

### E4 — Reindex tooling + (conditional) embedder/reranker bake-offs (L, conditional)

**✅ E4a (reindex CLI) COMPLETE — 2026-06-12; E4b (bake-offs) stays
DEFERRED under the models freeze.** `apps/api/app/cli/reindex.py`
(`python -m app.cli.reindex --tenant-id … [--document-id …]
[--after-document-id …] [--database-url …]`): streams the tenant's
documents from Postgres in stable id order, re-embeds leaf `search_text`
(persisted ADR-0020 `context_prefix` honored), re-upserts Qdrant +
OpenSearch with the **current** ACL payload
(`get_document_index_acl_metadata` — policy id/version, sensitivity rank,
expiry as of NOW, not the ingest-time stamp). Idempotent (deterministic
point/doc ids), resumable (`--after-document-id`, per-document boundary
logged), per-tenant scoped, truthful failure (no DB bind / out-of-tenant
ids / missing ACL grant; never substitutes stubs — `build_embedder` =
BGE-M3 per frozen ADR-0013, `build_vector_indexer`/`build_lexical_indexer`
map the existing qdrant_*/opensearch_* settings — the codebase's first
Settings→ingestion-indexer factories). Acceptance proven by the round-trip
test: ingest → reindex into fresh indexes → **identical ranked ids and
scores** (+ OpenSearch id-keyed `_source` equality + idempotent second
run), plus the ACL-freshness property (an `AclAllowedUser` grant added
after ingest reaches the reindexed payload while the live ingest-time
payload provably lacks it). 12 integration tests; suite **592 passed,
3 skipped**. Observed gap recorded for later wiring work: production
dispatcher construction (main.py + temporal worker) still defaults to
stub embedder/indexers — the new factories are the missing piece when
real index serving ships.

- **Files**: new management CLI `apps/api/app/cli/reindex.py` (or
  `scripts/reindex.py` — match repo conventions), ADR-0013/0014 reopen notes if
  triggered
- **Do**: (a) reindex CLI: stream chunks from Postgres → re-embed → re-upsert Qdrant
  + OpenSearch with the current ACL payload shape (needed by A5 and E2 anyway;
  idempotent, resumable, per-tenant scoped). (b) **Only if** Phase C numbers show
  headroom (recall@10 < 0.9 on the populated set) or the entry gate surfaced a
  materially better model: bake off Qwen3-Embedding-0.6B vs BGE-M3 and
  Qwen3-Reranker-0.6B vs bge-reranker-v2-m3 on the C3 rig, CPU latency measured
  alongside quality. Reopen ADR-0013/0014 only with that data.
- **Accept**: reindex CLI proven by round-trip test (ingest → reindex → identical
  retrieval results); bake-offs (if run) recorded in ADRs with quality *and* latency.

### E5 — Answering-LLM bake-off (ADR-0004 reopen, scheduled) (M)
- **Files**: `docs/uber-rag/adr/0004-llm-adapter-and-provider.md` (reopen note or
  superseding ADR), `tests/eval/reports/llm_bakeoff.json`, `.env`/config only —
  **zero code expected** (the ppq adapter is OpenAI-compatible; each candidate is
  `llm_model_name`/`llm_base_url` config)
- **Why now and not earlier**: Llama 3.3 70B (Dec 2024) shows no measured
  deficiency (faithfulness 1.000 not_contradicted, negative compliance 1.00) but
  is a stale default with an air-gap liability: 70B dense needs ~2× H100-class to
  serve locally, while the task — read-context, paraphrase, cite, refuse — is
  grounded QA that a well-chosen 20–32B-class model likely matches at a fraction
  of serving cost and TTFS (the only remaining ADR-0008 ~2s lever, Phase G).
  Phases C+D make the comparison cheap and honest; running it earlier would be
  vibes-based churn.
- **Do**: for the incumbent + each entry-gate-verified candidate, run the Phase C
  eval set (faithfulness via the Phase D verifier, negative-answer compliance,
  multilingual DE/PT subset) plus per-candidate cost/latency (ppq TTFS, $/Mtok).
  Decision rule, frozen before measuring: prefer the **smallest servable model**
  whose faithfulness and negative-compliance are within 0.02 of the incumbent and
  whose multilingual subset does not regress — smallest-that-wins buys the
  air-gap path and Phase G latency simultaneously.
- **Accept**: committed bake-off report; ADR-0004 reopened with the table and
  either superseded (new default named, license cited) or reconfirmed with data;
  production default flipped only via config after the ADR closes.

**Phase E exit criteria**: every retrieval upgrade either measurably improved the
committed baseline (and is config-default-on) or is documented as no-win and left
off. Baseline JSONs updated; CI gate thresholds re-pinned to the new baseline.
E5's ADR-0004 reopen is closed either way (superseded or reconfirmed with data).

**Phase E exit assessment — 2026-06-12 (within-freeze scope COMPLETE):**
every in-freeze upgrade was measured under a pre-frozen rule and is
documented either way — E1 expansion (deltas 0.0000, conformed + merged),
reranker arm (quality passes post-distractor, latency blocks the flip —
ADR-0014 reopen = ONNX/smaller-pool, unscheduled), E2 contextual
augmentation (ADR-0020 no-win, config-off), E3 query understanding
(ADR-0021 no-win, config-off), E4a reindex CLI (round-trip-proven).
Baseline JSONs and the CI gate remain pinned to the committed
post-distractor numbers (no flips occurred, so no re-pin was due). NOT
closable under the freeze: E4b bake-offs and E5 (ADR-0004 reopen) are
**deferred, not cancelled** — Phase E's last two boxes reactivate when the
freeze lifts; they do not block Phase F.

---

## Phase F — Book profile + frontend E2E (the original Phase 5)

**Goal**: both document profiles real; a non-engineer can upload, watch ingestion,
chat with citations, and inspect sources in a browser.
**Entry gate** (researcher): Docling current release notes (heading/page-anchor
extraction fidelity), Next.js 15 App Router stability check, Playwright vs Cypress
for the E2E rig (pick Playwright unless evidence says otherwise).

### F1 — Book profile chunker (L)
- **Files**: `apps/api/app/services/chunkers/book.py`, chunker factory/router by
  profile, `apps/api/app/services/chunkers/loose.py` untouched, schema additions
  (chapter/section identifiers, page anchors), tests with a real textbook PDF fixture
  parsed by Docling (commit a small public-domain textbook excerpt as fixture)
- **Do**: per ADR-0012's book direction: deep hierarchy (chapter → section →
  leaf), leaf 128–512 tok / parent 1024–2048 tok consistent with loose profile,
  heading-path breadcrumbs populated (this is what makes E2 breadcrumb mode shine on
  books), page anchors carried into chunk metadata → citations gain page numbers
  end-to-end (`page_start`/`page_end` already flow through `RetrievalHit`).
  Atomic tables/figures preserved like the loose chunker.
- **Accept**: textbook fixture chunks show correct hierarchy + page anchors;
  e2e ingestion test through the 7-stage pipeline with profile=book; loose-profile
  tests untouched and green.

### F2 — Profile selection at upload + profile-aware eval (S)
- **Files**: upload route/schema (`profile: Literal["loose","book"] = "loose"`),
  ingestion run metadata, eval fixtures gain ≥ 2 book documents, heldout textbook
  questions activated
- **Do (added 2026-06-12, pre-Phase-F ingestion)**: when authoring the activated
  textbook heldout questions, include a real multi-hop subset whose question
  shapes are sourced from the multi-hop benchmarks already in
  `STACK_REFERENCES.md` (MultiHop-RAG, MuSiQue, HotpotQA, 2WikiMultiHopQA) —
  E3 showed the current 5 `multi_hop` questions match the decompose
  heuristic's shapes 0/5 (the recorded trigger-shape gap), while its lone
  firing fully fixed a chapter-synthesis question (h49). Span-isolation
  invariant applies as always. Landing this subset fires **ADR-0021 reopen
  trigger 2**: re-run the decompose arm (heuristic, LLM-free, ~free) before
  citing its verdict.
- **Accept**: profile persisted and visible in ingestion jobs API; textbook subset of
  heldout runs against book-profile chunks (numbers recorded); if the multi-hop
  subset landed, the decompose arm re-run is recorded per ADR-0021 trigger 2.

### F3 — Frontend: finish the three pages + chat UI against the real API (L×2 sessions)
- **Files**: `apps/web/**`, `packages/clients/typescript/**`
- **Do**: session 1 — `npm ci`, fix the build, wire login (Keycloak OIDC code flow
  or dev-mode token), upload with progress, documents list, ingestion status (poll
  jobs API). Session 2 — chat page consuming the ADR-0018 SSE grammar (progressive
  sentences, retraction handling = replace text with not-enough-evidence message,
  citation chips → source viewer panel using
  `GET /api/v1/search/sources/{chunk_id}`), ACL editor (bootstrap policy GET/PUT).
  Regenerate the TS client from `docs/uber-rag/api/openapi.yaml`
  (openapi-typescript) instead of hand-writing types — contract drift becomes a
  build failure.
- **Accept**: `npm run build` green in CI (new job); manual flow documented with
  screenshots in the PR.

### F4 — Playwright E2E in CI (M)
- **Files**: `apps/web/e2e/**`, compose-based CI job (`AUTH_MODE=dev`, stub LLM,
  hybrid search against seeded fixture corpus)
- **Do**: one happy-path spec: login → upload fixture doc → wait ingestion complete →
  ask question → see streamed answer + citation → open source viewer. One ACL spec:
  Bob cannot see Alice's document in the UI.
- **Accept**: E2E job green in CI; flake-guarded (retries=1, explicit waits on API
  state not timeouts).

**Phase F exit criteria**: the ROADMAP Phase 5 sentence verbatim — "a non-engineer
can upload a textbook + a loose document, ask questions, see citations, see audit" —
demonstrated by the E2E suite.

---

## Phase G — Operational hardening (the original Phase 6)

**Goal**: deployable, observable, restorable, air-gap-ready.
**Entry gate** (researcher): OpenTelemetry GenAI semantic-conventions stability
status, Qdrant/OpenSearch snapshot APIs current docs, vLLM CPU/GPU serving status for
Llama-3.3-70B-class models (and smaller fallbacks), Keycloak production hardening
checklist.

### G1 — OpenTelemetry tracing + metrics (L)
- Spans per stage (parse/chunk/embed/index; route/retrieve/fuse/rerank/build-context/
  generate/verify-per-sentence) with privacy-safe attributes only (reuse the
  `query_sha256` discipline from search audit — never raw queries/answers in spans).
  GenAI semconv attribute names where stable. Prometheus metrics + a starter Grafana
  dashboard JSON in `infra/`. Config-gated exporter (`otel_enabled=false` default).
- **Accept**: trace screenshot of one chat request in the PR; overhead measured
  (< 5% on the load test).

### G2 — Backup/restore runbooks + drill (M)
- Snapshot scripts + runbooks for Postgres (pg_dump/WAL), Qdrant snapshot API,
  OpenSearch snapshot repo, MinIO/SeaweedFS object copy. One full restore drill onto
  a clean VM/compose stack, recorded step-by-step in `docs/uber-rag/runbooks/`.
- **Accept**: drill log committed; 12-point verification passes on the restored
  stack.

### G3 — Local LLM serving path (air-gap prerequisite) (M)
- The `LlmBackend` ppq adapter is OpenAI-compatible — point it at a local vLLM (or
  llama.cpp server) endpoint; add a compose profile for a small local model
  (e.g., Llama-3.x-8B-class) for smoke tests; document the 70B GPU requirements.
  Re-run the load test against local serving; this addresses ADR-0008's ~2s ambition
  and ADR-0017's revisit trigger.
- **Accept**: chat E2E green against local vLLM in a documented run; numbers
  recorded.

### G4 — Air-gap bundle + security review (L)
- Bundle: pinned container digests, all model weights (BGE-M3, reranker, verifier,
  local LLM), wheels, compose files, install script; install proven in a
  network-isolated VM. Security: `pip-audit` + `gitleaks` in CI, dependency review,
  threat-model doc refresh in `SECURITY_ACL.md`.
- **Accept**: ROADMAP Phase 6 exit criteria verbatim (restore drill recorded,
  benchmark report committed, air-gapped install runs).

---

## Phase H — Advanced retrieval menu (the original Phase 7, unchanged policy)

Open-ended, strictly eval-gated: each candidate needs (1) a measured weakness in the
Phase C/E reports, (2) an ADR with expected impact, (3) a bake-off on the C3 rig,
(4) ADR closure either way. The Phase C rig makes this phase *executable* for the
first time. Current menu (entry-gate refresh required before any pick):
GraphRAG/concept-graph for textbooks, HippoRAG-2-style multi-hop, LightRAG
comparison, RAPTOR-style hierarchical summarization (synergistic with the book
profile), BGE-M3 multivector (ColBERT-style) rerank stage, domain fine-tuned
embedder/reranker, table/formula reasoning.

Pick-order heuristic when the time comes: whatever the multi-hop/needle subset
numbers from C5/E3 say is weakest.

---

## 11. Open questions (executor: append here and stop — see contract rule 9)

*None at plan time. Architect assumptions, vetoable by the user:*
1. **Still no local GPU; ppq.ai remains the test-time LLM.** The plan is CPU/API-first
   throughout; GPU-only options are conditional (D entry-gate candidates, E4, G3).
2. **Retrieval SOTA (C–E) lands before the UI (F).** Rationale: measurement debt and
   verifier honesty are the platform's differentiators; the UI consumes whatever the
   API streams. F is deliberately parallelizable if a second executor exists.
3. **Ingest-time LLM cost for E2's `llm` arm is acceptable** (1 short call per chunk,
   config-gated, breadcrumb arm exists as the free alternative).
