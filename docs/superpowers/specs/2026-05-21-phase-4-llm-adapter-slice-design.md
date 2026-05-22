# Phase 4 LLM adapter first-slice design

Date: 2026-05-21
Status: Draft approved in chat, pending user review of written spec

## Goal

Implement the next executable Phase 4 slice by adding a standalone LLM-adapter seam between built context payloads and later `/chat` generation, without yet introducing the `/chat` endpoint, streaming, citation resolution, or verifier behavior.

## Why this slice first

The reranker and context-builder slices are already in place. The next clean dependency is the LLM adapter because it defines how the backend turns a user question plus evidence-backed context into a provider request and normalized model response. This keeps the architecture layered as retrieval -> rerank -> context build -> LLM adapter -> later `/chat`, and prevents `/chat` from absorbing provider-specific logic.

## Scope

In scope:

- Add an `LlmBackend` interface at the generation boundary.
- Add a deterministic stub backend for tests and disabled-runtime paths.
- Add a real OpenAI-compatible adapter for the accepted ppq.ai path.
- Accept user question, built context payload, and model/runtime settings.
- Return normalized generated-answer output plus provider/model metadata.
- Add truthful config/runtime failure behavior.
- Add unit coverage for request shaping, stub behavior, config validation, and failure paths.

Out of scope:

- `/chat` endpoint
- Streaming responses
- Citation resolver endpoint
- Sentence-level verifier
- Negative-answer behavior
- Final prompt policy tuning beyond the minimum provider request shape needed for this seam

## Architecture

Target flow for the next non-chat path:

1. Retrieval returns ACL-safe evidence hits.
2. Reranker orders the final evidence candidates.
3. Context builder emits structured context blocks.
4. `LlmBackend` receives the user question plus structured context payload.
5. The adapter constructs a provider request for the configured backend.
6. The adapter returns a normalized response object containing answer text and model/provider metadata.
7. Later Phase 4 slices will wrap this seam in `/chat`, streaming, citation, and verifier logic.

The adapter does not own retrieval, ACL, reranking, context assembly, or citation verification. It only handles provider-bound generation transport and response normalization.

## Interfaces and responsibilities

### `LlmBackend` interface

Responsibilities:

- Accept a normalized generation request.
- Convert that request into a provider call.
- Return a normalized generation response.
- Keep provider-specific transport hidden behind one seam.

Non-responsibilities:

- Retrieval
- ACL filtering
- Reranking
- Context building
- Citation validation
- HTTP route behavior

### `StubLlmBackend`

Responsibilities:

- Return deterministic answer text for tests.
- Preserve request/response shape without external network calls.
- Support disabled/local test execution cleanly.

### OpenAI-compatible ppq adapter

Responsibilities:

- Use the accepted OpenAI-compatible provider path.
- Shape system/user messages from the normalized generation request.
- Return answer text plus provider/model metadata.

Constraints:

- Missing required config must fail truthfully.
- Unsupported backend names must fail clearly.
- No silent fallback from configured real backend to stub.

## Data contracts

### Generation request

The input request should carry:

- `question`
- `context_payload`
- `model_name`
- optional generation knobs such as temperature and max output tokens

The adapter may render the context payload into a provider-facing message string internally, but the seam boundary should stay structured rather than passing ad-hoc prompt strings from callers.

### Generation response

The output response should carry:

- `answer_text`
- `model_name`
- `provider_name`
- optional raw usage metadata if returned by the provider

This slice does not need final citation extraction or verifier outputs yet.

## Request shaping

Initial rule set:

- Use a deterministic system instruction emphasizing source-bound answers.
- Render context blocks in stable order.
- Include document title, citation identifier, and block text in the provider-facing context section.
- Append the user question after the evidence context.

This keeps the provider request stable and testable before `/chat` exists.

## Configuration

Add explicit runtime configuration for:

- LLM backend selection (`disabled`, `stub`, `ppq` or equivalent naming)
- provider base URL if required
- API key
- default model name
- default temperature
- default max output tokens

Rules:

- Disabled/stub paths must remain usable without network credentials.
- Real backend config must fail clearly if required fields are missing.

## Error handling

- Disabled backend must not masquerade as a real provider path.
- Missing API key or base URL for a real backend must raise a truthful startup/runtime error.
- Unsupported backend names must fail clearly.
- Empty context payload is allowed for this seam, but later `/chat` policy may choose to reject or special-case it.
- Empty provider response text must fail clearly rather than pretending generation succeeded.

## Testing

Minimum coverage:

- stub backend returns deterministic normalized output
- config validation for backend selection and required real-backend fields
- request shaping includes context blocks in stable order
- request shaping includes question and citation-bearing context metadata
- unsupported backend fails truthfully
- real adapter response normalization handles provider output correctly

## Acceptance criteria

- A standalone `LlmBackend` seam exists.
- A deterministic stub backend exists for tests.
- A real OpenAI-compatible ppq adapter is wired behind config.
- Request shaping is deterministic and covered by tests.
- Missing/invalid real-backend config fails truthfully.
- Targeted tests pass.

## Risks

- The current provider request shape may need refinement once `/chat` and citation rendering arrive.
- Provider SDK choice must stay lightweight and replaceable.
- Empty-context generation policy is intentionally deferred and may need tightening in the `/chat` slice.

## Follow-on work unlocked by this slice

1. Non-streaming `/chat`
2. Streaming `/chat`
3. Citation resolver
4. Sentence-level verifier
5. Negative-answer behavior
