# Phase 4 context builder first-slice design

Date: 2026-05-21
Status: Draft approved in chat, pending user review of written spec

## Goal

Implement the next executable Phase 4 slice by adding a standalone, deterministic context-builder seam between reranked retrieval results and later LLM generation, without yet introducing the LLM adapter, `/chat`, streaming, or verifier behavior.

## Why this slice first

The reranker slice is already in place. The next clean dependency is the context builder because it defines exactly what evidence payload later generation will consume. This keeps the Phase 4 architecture layered as retrieval -> rerank -> context build -> generation, and avoids baking prompt or `/chat` decisions into retrieval code too early.

## Scope

In scope:

- Add a `ContextBuilder` interface at the retrieval/generation boundary.
- Add a deterministic default implementation.
- Accept ordered reranked hits plus budget settings.
- Emit structured context blocks that preserve citation metadata.
- Enforce a simple, stable truncation budget.
- Add unit coverage for ordering, trimming, metadata preservation, and empty input behavior.

Out of scope:

- LLM adapter
- Prompt templates for final generation
- `/chat` endpoint
- Streaming responses
- Citation resolver endpoint
- Sentence-level verifier
- Negative-answer behavior

## Architecture

Target flow for the next non-chat path:

1. Query router classifies the request.
2. OpenSearch and Qdrant retrieval run with ACL-safe filters.
3. Fusion combines candidates.
4. Parent-child expansion runs.
5. Reranker orders the final evidence candidates.
6. `ContextBuilder` converts those candidates into structured, budgeted context blocks.
7. Later Phase 4 slices will hand those context blocks into generation.

The context builder does not fetch data, alter ACL policy, or generate answers. It is only responsible for turning already-approved evidence hits into an LLM-ready context payload.

## Interfaces and responsibilities

### `ContextBuilder` interface

Responsibilities:

- Accept an ordered list of retrieval hits.
- Accept explicit context-budget settings.
- Return a deterministic, structured context payload.
- Preserve source metadata needed for later citation rendering.

Non-responsibilities:

- Retrieval
- ACL filtering
- Reranking
- Prompt wording
- Answer generation

### Default context builder

Responsibilities:

- Preserve reranker order.
- Convert each selected hit into a structured context block.
- Apply a stable budget rule before returning the payload.
- Exclude hits that do not contain usable evidence text.

## Data contracts

Each emitted context block should carry enough information for later answer-generation and citation rendering:

- `document_id`
- `document_title`
- `chunk_id`
- `citation_id`
- `text`
- `heading_path`
- `page_start`
- `page_end`
- `rank`

The top-level context payload should carry:

- ordered `blocks`
- block count
- total character budget used
- whether truncation occurred

This slice can use a character-count budget rather than a tokenizer-specific token budget so the implementation stays deterministic and dependency-light. If needed later, Phase 4 can swap this to tokenizer-aware budgeting behind the same seam.

## Budgeting and truncation

Initial rule set:

- Consume reranked hits in order.
- Skip empty-text hits.
- Add whole blocks until the configured total character budget would be exceeded.
- If the next block would overflow the budget, truncate only that block's text to the remaining budget if the remainder is meaningful; otherwise stop.
- Mark the payload as truncated when any hit text is shortened or omitted because of budget.

This preserves deterministic behavior and avoids hidden reordering.

## Configuration

Add explicit runtime configuration for:

- default context character budget
- optional maximum number of context blocks

Rules:

- The context builder must remain usable without an LLM backend configured.
- Defaults should be conservative and easy to reason about.

## Error handling

- Empty input returns an empty context payload.
- Hits with blank text are skipped.
- Missing optional metadata such as page range or heading path must not fail context assembly.
- Budget values must be validated at entry points or fail clearly if invalid.

## Testing

Minimum coverage:

- preserves reranked order in emitted blocks
- trims context deterministically to the configured budget
- preserves citation/source metadata in blocks
- returns an empty payload for empty input
- skips blank-text hits
- respects maximum-block count if configured

## Acceptance criteria

- A standalone `ContextBuilder` seam exists.
- The default implementation returns deterministic, structured context blocks.
- Citation metadata survives unchanged into the context payload.
- Budget trimming is explicit and covered by tests.
- Targeted tests pass.

## Risks

- Character-count budgeting is a simplification and may not perfectly match later model token limits.
- Current search hit shapes may require a small adapter layer if document-title metadata is not consistently available at the builder boundary.
- Overly aggressive truncation could weaken later answer quality if budgets are set too low.

## Follow-on work unlocked by this slice

1. Prompt assembly
2. LLM adapter
3. Non-streaming `/chat`
4. Streaming `/chat`
5. Citation resolver
6. Sentence-level verifier
7. Negative-answer behavior
