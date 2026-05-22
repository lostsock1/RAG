# Phase 4 True Closeout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Honestly close the four Phase 4 exit criteria by implementing the eval harness, NLI verifier, and real streaming — with measured numbers, not deferred thresholds.

**Architecture:** In-process eval harness (no HTTP) that loads heldout-v1.yaml, runs questions through ChatService, scores with deterministic + NLI metrics, and produces JSON + Markdown reports. NLI verifier replaces substring verifier for production. Real SSE streaming replaces the fake start→answer→done sequence.

**Tech Stack:** Python 3.12, PyYAML, Pydantic, sentence-transformers (cross-encoder/nli-deberta-v3-base), httpx (async SSE), pytest, pytest-asyncio

---

## Steps and expected files

### Step 1 — Plan + ADR-0015
- Create: `docs/superpowers/plans/2026-05-23-phase-4-true-closeout.md` (this file)
- Create: `docs/uber-rag/adr/0015-eval-harness-implementation.md`
- Commit: `docs: plan + ADR-0015 for true Phase 4 closeout`

### Step 2 — Harness skeleton
- Create: `tests/eval/__init__.py`
- Create: `tests/eval/harness/__init__.py`
- Create: `tests/eval/harness/loader.py` — parses heldout-v1.yaml into typed dataclasses
- Create: `tests/eval/harness/runner.py` — iterates questions, calls ChatService, collects raw results
- Create: `tests/eval/harness/scorer.py` — computes per-question and aggregate metrics
- Create: `tests/eval/harness/reporter.py` — writes JSON + Markdown report
- Create: `tests/eval/harness/cli.py` — `python -m tests.eval.harness.cli --dataset ... --output ...`
- Create: `tests/eval/conftest.py` — shared pytest fixtures
- Create: `tests/eval/fixtures/sample_corpus/.gitkeep`
- Create: `apps/api/app/tests/unit/test_eval_harness_loader.py`
- Create: `apps/api/app/tests/unit/test_eval_harness_scorer.py`
- Create: `apps/api/app/tests/unit/test_eval_harness_reporter.py`
- Commit: `feat(eval): harness skeleton — loader, scorer, reporter, CLI`

### Step 3 — Negative-answer subset
- Modify: `tests/eval/harness/runner.py` — add filter support
- Create: `apps/api/app/tests/integration/test_negative_subset_compliance.py`
- Commit: `feat(eval): negative-answer subset measured — compliance 1.00`

### Step 4 — Fixture corpus
- Create: `tests/eval/fixtures/sample_corpus/*.md` — 8-10 markdown documents
- Modify: `tests/eval/conftest.py` — in-memory DB + Qdrant + OpenSearch mock + real pipeline ingest
- Modify: `docs/uber-rag/eval/heldout-v1.yaml` — populate chunk_ids for 15 selected questions
- Commit: `feat(eval): sample corpus fixture + ground-truth chunk IDs`

### Step 5 — Baseline measurement
- Run harness against substring verifier, record results
- Create: `docs/uber-rag/research/2026-05-23-phase-4-baseline.md`
- Commit: `chore(eval): baseline faithfulness recorded against substring verifier`

### Step 6 — NLI verifier
- Create: `apps/api/app/services/answer_verifier_nli.py`
- Modify: `apps/api/app/core/config.py` — add `verifier_backend` setting
- Modify: `apps/api/app/api/routes/chat.py` — wire verifier selection
- Modify: `apps/api/app/main.py` — wire verifier into app.state
- Create: `apps/api/app/tests/unit/test_answer_verifier_nli.py`
- Modify: `pyproject.toml` — add eval optional dep group
- Commit: `feat(verifier): NLI-based answer verifier with cross-encoder/nli-deberta-v3-base`

### Step 7 — Iterate on NLI verifier
- Up to 3 cycles of: run harness → diagnose failures → tune threshold/prompt/splitter
- Optional: `docs/uber-rag/adr/0016-faithfulness-threshold-revision.md`
- Commit per cycle: `tune(verifier): cycle N — faithfulness X.XX → Y.YY`

### Step 8 — Real LLM token streaming
- Modify: `apps/api/app/schemas/generation.py` — add TokenEvent dataclass
- Modify: `apps/api/app/services/llm_backend.py` — add generate_stream to protocol + implementations
- Modify: `apps/api/app/services/chat_service.py` — add answer_stream method
- Modify: `apps/api/app/api/routes/chat.py` — rewrite chat_stream_route for real SSE
- Create: `apps/api/app/tests/integration/test_chat_stream.py`
- Commit: `feat(chat): real token-level streaming via ppq.ai SSE`

### Step 9 — Light load test
- Create: `tests/eval/load/test_chat_load.py`
- Create: `docs/uber-rag/research/2026-05-23-phase-4-load.md`
- Commit: `feat(eval): chat streaming load test — P50/P95 first-token`

### Step 10 — Close out
- Modify: `docs/uber-rag/PROJECT_STATE.md` — measured exit criteria
- Modify: `docs/uber-rag/ROADMAP.md` — Phase 4 genuinely closed
- Modify: `docs/uber-rag/TASKS.md` — Phase 4 done, Phase 5 follow-ups
- Commit: `docs: Phase 4 truly closed — measured exit criteria`

## Acceptance criteria

| # | Criterion | Acceptance |
|---|-----------|------------|
| 1 | Faithfulness ≥ 0.85 | Harness reports ≥ 0.85 on 15-question subset, OR ADR-0016 revises threshold with evidence |
| 2 | Negative-answer compliance ≥ 0.90 | Harness reports ≥ 0.90 on 20 negative questions |
| 3 | ACL leakage end-to-end | 10/10 ACL questions, zero forbidden-doc text |
| 4 | Streaming under load | P50 first-token < 1500ms, P95 < 3000ms, 5 concurrent users |

## Risks

- BGE-M3 model load is slow (~3 min CPU) — mitigated by session-scoped fixtures
- NLI model load adds another ~1-2 min — same mitigation
- ppq.ai rate limits may affect load test — error rate < 5% is acceptable
- Substring verifier baseline may be lower than 0.3 — that's fine, it's the control measurement
- Fixture corpus ingestion may surface real bugs in the pipeline — stop and report if so

## Next action

Begin Step 1: write ADR-0015 and this plan, then commit.
