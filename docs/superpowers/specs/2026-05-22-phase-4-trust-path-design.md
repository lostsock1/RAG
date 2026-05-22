# Phase 4 trust-path completion design

Date: 2026-05-22
Status: Draft approved in chat, pending user review of written spec

## Goal

Complete the Phase 4 trust-critical backend path by adding citation resolution, sentence-level evidence verification, and hardened insufficient-evidence behavior before broader UI or evaluation work.

## Why this route first

The project already has ingestion, indexing, hybrid retrieval, reranking, context building, and a first `/chat` + `/chat/stream` slice. The main remaining risk is answer trustworthiness, not transport or UI breadth. The architecture already commits to source-bound answers and sentence-level verification, so the strongest next move is to finish those backend guarantees before adding more product surface.

This route keeps the current architecture intact:

1. retrieval remains the only source of evidence
2. context builder remains the only prompt-context producer
3. generation remains behind the `LlmBackend` seam
4. new trust layers sit after generation and before final response shaping

## Scope

In scope:

- Add a citation resolver service boundary and public resolution endpoint.
- Add a sentence-level verifier service boundary and public verification endpoint.
- Integrate both into the existing chat orchestration path.
- Add hardened negative-answer policy driven by verifier output.
- Update API contract and OpenAPI for the new truthful Phase 4 behavior.
- Add unit and integration coverage for the trust path.
- Add enough structured outputs so the later evaluation harness can measure citation correctness, supported-claim rate, and not-found accuracy.

Out of scope:

- Book-profile chunking
- Broader UI work
- Eval dashboard
- Model swaps or new stack ADRs unless implementation reveals a real blocker
- Full conversational memory/session persistence
- Provider-specific token-by-token verification logic

## Current baseline

The current chat path reuses ACL-safe retrieval and returns a normalized answer payload, but it does not yet resolve citations, verify sentence support, or fail closed after generation. If retrieval yields no usable evidence, the service already returns a truthful not-enough-evidence message before the LLM is called. The new work extends that evidence discipline to the post-generation path.

## Architecture

Target runtime flow:

1. `/chat` or `/chat/stream` accepts an authenticated question.
2. `ChatService` calls the existing ACL-safe retrieval path.
3. `ContextBuilder` builds ordered context blocks from authorized hits.
4. `LlmBackend` generates a draft answer from question + context.
5. `SentenceVerifier` checks each answer unit against the authorized context blocks.
6. `CitationResolver` emits normalized citations only for resolvable authorized evidence.
7. Negative-answer policy decides whether to:
   - return a verified answer with citations, or
   - replace/trim unsupported output with a normalized insufficient-evidence response.
8. Route returns the final normalized payload and writes audit details about verification outcome.

This preserves the current layering. Routes remain thin transport adapters over shared orchestration logic.

## Component boundaries

### 1. Citation resolver

Purpose: convert internal evidence references into stable user-facing citations.

Responsibilities:

- Accept retrieval/context references from authorized hits only.
- Map references to stable chunk/document/source-viewer metadata.
- Drop unresolved or unauthorized references instead of inventing placeholders.
- Return deterministic citation objects for `/chat`, `/chat/stream`, and `POST /api/v1/citations/resolve`.

Non-responsibilities:

- Fetching unauthorized source text
- Re-running retrieval
- Deciding whether the answer is sufficiently supported

### 2. Sentence verifier

Purpose: determine whether each answer unit is supported by authorized evidence.

Responsibilities:

- Split the generated answer into verification units using deterministic sentence/paragraph boundaries.
- Compare each unit against the retrieved context blocks.
- Mark each unit as `supported`, `unsupported`, or `insufficient_evidence`.
- Attach supporting citation ids where support exists.
- Produce a structured verification result consumable by chat policy and later evaluation.

Non-responsibilities:

- Retrieval
- Prompt construction
- Final response transport

Initial verifier strategy:

- Start with deterministic lexical/overlap heuristics against the authorized context blocks.
- Make the verifier interface swappable so a stronger model-assisted verifier can be introduced later without route or schema rewrites.

### 3. Negative-answer policy

Purpose: enforce fail-closed behavior when answer support is weak.

Responsibilities:

- Define minimum support conditions for returning an answer as `answered`.
- Replace fully unsupported answers with the normalized insufficient-evidence response.
- Optionally trim unsupported sections if the remaining supported content still clears the minimum threshold.
- Return safe follow-up guidance only if it can be phrased without overclaiming.

Non-responsibilities:

- Creating evidence
- Provider-specific prompting tricks

## Data contracts

### Chat response evolution

The current chat response should be extended rather than replaced.

Additional fields should include:

- `citations`: normalized citation objects
- `verification`: structured summary with per-unit or aggregated support status
- `status`: continue to expose `answered|not_enough_evidence`, but now driven by post-generation verification as well as pre-generation evidence presence

Truthful rule: if support is weak, the API must not return a confident answer body merely because the LLM produced one.

### Citation object

Minimum fields:

- `citation_id`
- `document_id`
- `document_title`
- `chunk_id`
- `source_viewer_url`
- `page_start`
- `page_end`
- `heading_path`

Only include fields that are actually resolvable from indexed chunk metadata.

### Verification result

Minimum structure:

- overall verification status
- total answer unit count
- supported unit count
- unsupported unit count
- insufficient-evidence unit count
- per-unit support records including matched citation ids where available

### Public endpoints

The existing target contract already includes:

- `POST /api/v1/citations/resolve`
- `POST /api/v1/answers/verify`

This slice should make those endpoints truthful and usable with the same core services the chat path uses.

## Error handling

- If retrieval is unavailable, chat continues to fail clearly with `503`.
- If generation is unavailable, chat continues to fail clearly with `503`.
- If retrieval returns zero usable hits or context construction yields zero blocks, chat returns the existing insufficient-evidence response without invoking the LLM.
- If generation succeeds but verification shows insufficient support, the final response must become `not_enough_evidence` rather than exposing unsupported text as a final answer.
- If citation resolution cannot resolve a claimed citation, the unresolved citation is omitted and the verifier/policy layer must not count it as support.
- Streaming must never imply verified partial support that does not yet exist. For the first trust slice, it is acceptable for `/chat/stream` to emit the final verified answer payload only after verification completes.

## Security and ACL

- Citation resolution must operate only on ACL-safe retrieval outputs.
- No route may accept raw privileged context from the client.
- Source-viewer access remains ACL-gated at fetch time.
- Verification must only inspect authorized evidence blocks already returned by retrieval/context construction.
- Audit events should record verification outcome and citation counts, but not raw question text.

## Testing

### Unit coverage

- citation resolver returns stable citation objects from resolvable hits
- citation resolver drops unresolved references without fabricating broken pointers
- sentence verifier marks supported vs unsupported units deterministically
- negative-answer policy converts unsupported answers into the normalized insufficient-evidence response

### Integration coverage

- `/chat` returns verified answer payload with citations when support is sufficient
- `/chat` returns `not_enough_evidence` when verification fails after generation
- `/chat/stream` returns a truthful final verified payload sequence
- `/citations/resolve` returns only resolvable authorized citations
- `/answers/verify` returns structured verification results without bypassing ACL

### Regression coverage

- unresolved chunk ids do not produce broken citation URLs
- unsupported sentences do not survive into an `answered` response
- denied source citations do not leak text or metadata beyond the existing not-found/denied contract
- audit events store verification metadata without storing plaintext query text

## Acceptance criteria

- `CitationResolver` service exists and is wired into chat plus a public resolution endpoint.
- `SentenceVerifier` service exists and is wired into chat plus a public verification endpoint.
- Chat answer status reflects post-generation verification, not just generation success.
- Insufficient-evidence behavior is fail-closed and truthful.
- Targeted unit and integration tests pass.
- API contract docs and OpenAPI match the implemented Phase 4 behavior.

## Risks

- Naive sentence splitting may behave poorly on formatted or multilingual output.
- Deterministic heuristics may under-call support on paraphrased answers.
- Tight coupling between verifier output and chat schema could create rework if not kept modular.

## Mitigations

- Keep the verifier behind a small explicit interface.
- Start deterministic and conservative; false negatives are safer than false positives for this phase.
- Keep citation resolution pure and metadata-driven.
- Extend existing response schemas incrementally rather than redesigning them wholesale.

## Recommended implementation order

1. Citation resolver
2. Sentence verifier
3. Negative-answer policy integration into `ChatService`
4. Public `/citations/resolve` and `/answers/verify` endpoints
5. API/OpenAPI truthfulness updates
6. Targeted regression and verification passes

## Follow-on work unlocked by this slice

1. Evaluation harness implementation against real trust-path outputs
2. UI citation rendering and source viewer integration
3. Richer streaming semantics once verification-aware transport is needed
4. Stronger verifier backends if deterministic heuristics prove too weak
