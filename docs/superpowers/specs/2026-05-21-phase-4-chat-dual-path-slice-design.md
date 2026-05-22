# Phase 4 chat dual-path first-slice design

Date: 2026-05-21
Status: Draft approved in chat, pending user review of written spec

## Goal

Implement the first user-facing Phase 4 chat slice by adding a shared chat orchestration service plus both non-streaming and streaming `/chat` API paths, without yet introducing citation resolution or sentence-level verification.

## Why this slice first

The reranker, context builder, and LLM adapter seams are already in place. The next clean slice is a thin `/chat` layer that composes them. Building non-streaming and streaming together around one shared orchestration path avoids duplicating business logic and reduces rework in route contracts.

## Scope

In scope:

- Add chat request/response schemas.
- Add a shared `ChatService` orchestration layer.
- Add non-streaming `/chat`.
- Add streaming `/chat` using the same service path and minimal event framing.
- Return truthful service failures when retrieval or generation is unavailable.
- Add unit/integration coverage for both paths.

Out of scope:

- Citation resolver endpoint
- Sentence-level verifier
- Negative-answer policy beyond current provider/system-instruction behavior
- Persistent conversation/session memory
- Final polished stream protocol beyond a thin stable first slice

## Architecture

Target flow for both chat paths:

1. Route accepts authenticated chat request.
2. `ChatService` builds a search query from the user question.
3. Retrieval runs through the existing ACL-safe search path.
4. Context builder turns the returned evidence hits into context blocks.
5. LLM backend generates the answer from question + context payload.
6. Route returns the normalized answer either:
   - as one JSON response for non-streaming, or
   - as a minimal sequence of stream events for streaming.

The route layer should not duplicate retrieval/context/generation logic. Streaming is a transport variant over the same orchestration result.

## Interfaces and responsibilities

### `ChatService`

Responsibilities:

- Accept request context plus chat payload.
- Call retrieval.
- Build context payload.
- Call the LLM backend.
- Return a normalized chat result for route adapters.

Non-responsibilities:

- Citation verification
- Session persistence
- Stream transport details

### Non-streaming route

Responsibilities:

- Validate request.
- Call `ChatService`.
- Return full answer payload.

### Streaming route

Responsibilities:

- Validate request.
- Call `ChatService` through the same orchestration path.
- Emit a minimal stable event sequence.

## Data contracts

### Chat request

Should carry:

- `question`
- optional `top_k` override for retrieval
- optional `stream` flag only if needed by the public contract; otherwise keep streaming as a separate endpoint

### Chat response

Non-streaming response should carry:

- `answer_text`
- `model_name`
- `provider_name`
- optional usage metadata
- context summary fields if useful and already available without inventing new semantics

### Streaming events

Initial minimal sequence:

1. `start`
2. `answer`
3. `done`

This slice does not need token-by-token generation from the upstream provider. It is acceptable for the first streaming implementation to stream the final answer as one answer event, as long as the transport contract is truthful and ready for later chunking.

## Error handling

- If retrieval is unavailable, return truthful service failure.
- If generation is unavailable, return truthful service failure.
- If retrieval returns no usable evidence blocks, return a clear not-ready/not-enough-evidence response only if the current architecture can do so truthfully; otherwise fail clearly and defer final negative-answer policy to the later slice.
- Streaming path must emit a terminal error or fail clearly; it must not hang silently.

## Security and evidence discipline

- The chat path must only use ACL-filtered retrieval outputs.
- Frontend/API contract must not let clients supply privileged context directly.
- LLM input must come only from the system instruction, the user question, and the context builder output.
- Do not claim citation fidelity beyond what this slice actually returns.

## Testing

Minimum coverage:

- non-streaming `/chat` returns normalized answer payload using the shared service
- streaming path emits `start` -> `answer` -> `done`
- both routes use the same orchestration path
- unavailable retrieval/generation fails truthfully
- ACL-safe request context still gates visible documents through the existing retrieval path

## Acceptance criteria

- Shared `ChatService` exists.
- Non-streaming `/chat` works.
- Streaming `/chat` works with a minimal truthful event protocol.
- Both paths reuse the same orchestration logic.
- Targeted tests pass.

## Risks

- Without citation resolver/verifier, answer payload must stay modest in what it claims.
- First streaming version may be structurally streaming rather than token-streaming; that is acceptable only if documented truthfully.
- Chat route integration may expose gaps in how retrieval results and context-builder metadata flow together.

## Follow-on work unlocked by this slice

1. Citation resolver
2. Sentence-level verifier
3. Negative-answer behavior hardening
4. Richer streaming/chunked token transport
