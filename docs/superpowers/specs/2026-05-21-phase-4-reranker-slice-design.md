# Phase 4 reranker first-slice design

Date: 2026-05-21
Status: Draft approved in chat, pending user review of written spec

## Goal

Implement the first executable Phase 4 slice by adding a model-swappable reranker seam and wiring a real `bge-reranker-v2-m3` adapter into the retrieval pipeline without yet introducing `/chat`, streaming, or context-builder behavior.

## Why this slice first

Phase 3 search is complete and Phase 4 begins with reranking, generation, and verification (`docs/uber-rag/PROJECT_STATE.md`). The reranker is the narrowest high-value insertion point between retrieval and later answer generation. It improves ranking quality before context assembly and LLM generation, reducing rework in later `/chat` work.

## Scope

In scope:

- Add a `Reranker` interface in the retrieval layer.
- Add a stub/no-op reranker for tests and non-model runtime paths.
- Add a real `bge-reranker-v2-m3` adapter behind configuration.
- Wire reranking into the hybrid retrieval flow after fusion and before final result selection.
- Preserve exact-match and other explicit lexical-bypass routes so deterministic exact retrieval does not pay reranker latency.
- Add unit and integration coverage for reranking behavior, bypass behavior, and runtime wiring.

Out of scope:

- Context builder
- `/chat` endpoint
- Streaming responses
- Citation resolver endpoint
- Sentence-level verifier
- Negative-answer response logic

## Architecture

Target flow for non-bypass search paths:

1. Query router classifies the request.
2. OpenSearch and Qdrant retrieval run with ACL-safe filters.
3. Reciprocal-rank fusion combines candidates.
4. Parent-child expansion runs if already required by the existing search path.
5. `Reranker` scores the candidate set.
6. Final top-k results are returned to the caller.

Target flow for exact-bypass paths:

1. Query router identifies exact/quoted/identifier-style retrieval.
2. Lexical retrieval executes.
3. Results bypass reranking and return directly.

This preserves current search truthfulness and the Phase 3 exact-string guarantee.

## Interfaces and responsibilities

### `Reranker` interface

Responsibilities:

- Accept the user query plus an ordered candidate list.
- Return the same candidates with rerank scores and updated ordering.
- Remain storage-backend-neutral and model-neutral.

Non-responsibilities:

- Fetching candidates
- ACL filtering
- Citation formatting
- Context building

### `StubReranker`

Responsibilities:

- Preserve deterministic ordering for tests or disabled-model runtime.
- Expose the same interface as the real reranker.

### `BgeRerankerV2M3`

Responsibilities:

- Load the accepted default reranker model lazily.
- Score query-document pairs in batches.
- Return deterministic descending-score ordering for the candidate set.

Constraints:

- CPU-first local development path must work.
- Runtime wiring must fail truthfully if reranking is enabled but the adapter cannot initialize.
- No silent fallback from real reranker to stub in production-style runtime.

## Data flow and contracts

- The reranker consumes already ACL-filtered, already fused candidate results.
- Candidate records must include the text needed for reranking plus stable metadata needed later by citations and source viewing.
- Reranking must not strip or mutate ACL metadata.
- The returned result shape should preserve existing search response compatibility unless a field addition is explicitly documented.

## Configuration

Add explicit runtime configuration for:

- reranker backend selection (`disabled` / `stub` / `bge-reranker-v2-m3` or equivalent project naming)
- model name override if needed
- batch size / top-k candidate limit for reranking

Rules:

- Safe local default may remain disabled or stub until the model dependency is intentionally enabled.
- If the configured real reranker is unavailable, startup or runtime must fail with a clear message rather than silently degrading.

## Error handling

- If reranking is disabled, retrieval proceeds without reranking by explicit configuration.
- If reranking is enabled but model initialization fails, return a truthful service error or fail startup depending on current runtime construction patterns.
- If the candidate set is empty, reranker is skipped.
- If the query is on a bypass route, reranker is skipped.

## Testing

Minimum coverage:

- `Reranker` interface contract tests
- stub reranker ordering test
- exact/quoted/identifier query bypass tests
- hybrid retrieval path test proving reranker is invoked for non-bypass routes
- runtime configuration tests for enabled/disabled/invalid reranker setup
- adapter tests for score ordering and deterministic shape handling

If model-dependent tests are slow, keep them isolated and guard them the same way the BGE-M3 embedder tests are handled now.

## Acceptance criteria

- A model-swappable `Reranker` seam exists in the retrieval layer.
- The real `bge-reranker-v2-m3` adapter is wired behind config.
- Non-bypass hybrid retrieval routes invoke reranking.
- Exact lexical routes bypass reranking.
- Existing ACL guarantees remain unchanged.
- Existing search contract remains truthful.
- Targeted tests pass.

## Risks

- CPU latency may be high if reranking too many candidates; top-k pre-trimming must stay explicit.
- Candidate records may need small schema adjustments if current retrieval results do not consistently carry the text required for query-document pair scoring.
- Runtime dependency footprint may increase, so failure messaging must stay precise.

## Follow-on work unlocked by this slice

1. Context builder
2. LLM adapter
3. Non-streaming `/chat`
4. Streaming `/chat`
5. Citation resolver
6. Sentence-level verifier
7. Negative-answer behavior
