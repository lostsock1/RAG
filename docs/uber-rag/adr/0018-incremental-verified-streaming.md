# ADR-0018: Sentence-Incremental Verified Streaming

Status: Accepted
Date: 2026-06-10

## Context

The 2026-05-23 evidence-discipline fix (commit `1ce0d30`) made `/api/v1/chat/stream`
buffer **every** generated token until post-generation verification passes. This
preserved architecture invariant #5 (no unsupported text ever reaches the client)
but destroyed time-to-first-token: the 2026-06-10 re-measurement
(`tests/eval/reports/load_post_buffering.json`) shows P50 first-verified-token
**5.97s** and P95 **10.75s** — both violating the ADR-0017 SLA (5s/10s), with
`first_token ≈ total` on every request. ADR-0017 is marked "failing by design"
pending this ADR.

Two facts make a better design possible:

1. The verifier (`NliAnswerVerifier`, `AnswerVerifier`, pass-through) already
   scores **per sentence**, splitting on `re.split(r"(?<=[.!?])\s+", text)`, and
   each sentence is scored against context blocks independently. Verifying one
   sentence at a time through the existing `verify()` interface produces
   *identical scores* to verifying the whole answer — only the aggregation
   differs.
2. Most answers pass verification (measured faithfulness 1.000 in
   `not_contradicted` mode), so the happy path dominates.

## Decision

Stream **verified sentences incrementally**: assemble LLM tokens into sentences
as they arrive, verify each completed sentence against the already-built context,
and emit each sentence's text the moment it passes. No text is ever emitted
before its sentence is verified — the evidence invariant is preserved at finer
granularity than before, and TTFT drops from ~full-answer latency to
~first-sentence latency.

### 1. Sentence assembly

A `SentenceAssembler` (new `app/services/streaming_verifier.py`) accumulates
streamed token text and yields completed sentences using the **same boundary
regex as the verifiers** (`(?<=[.!?])\s+`), preserving the original text exactly
(trailing whitespace attaches to the completed sentence) so that the
concatenation of emitted token events reproduces the generated text verbatim.
On stream end, `flush()` yields the trailing remainder as the final sentence
(whitespace-only remainders are dropped). Consistency with the verifier's own
splitter is deliberate; abbreviation edge cases ("Dr. Smith") split identically
in both places, which is what matters.

### 2. Per-sentence verification gate

Each completed sentence is passed to the existing
`verify(answer_text=<sentence>, context_payload=...)` and gated on the returned
`summary.status == "supported"`. Citation IDs are collected from the summary's
sentence entries.

**Strictness divergence (deliberate):** the blocking `/chat` path tolerates up
to `nli_unsupported_ratio` (default 0.2) unsupported sentences in an accepted
answer. The streaming path cannot honestly do that — at emission time a sentence
is either verified or it is not, and emitting a sentence the verifier has
*already flagged* would violate the invariant directly. Streaming is therefore
**stricter** than blocking: a 5-sentence answer with one contradicted sentence
is accepted by `/chat` (ratio 0.2 ≤ 0.2) but triggers the failure policy on
`/chat/stream`. This divergence is acceptable because it errs toward safety;
it is documented in `API_CONTRACT.md`.

### 3. Inline verification, in a worker thread (amends the master-plan sketch)

The master plan sketched pipelined verification (verify sentence N while N+1
streams, ordered emission queue). This ADR **amends that to inline-await v1**:
on each sentence boundary, `await anyio.to_thread.run_sync(verify, ...)`, then
emit, then continue consuming the LLM stream.

Why:

- Background tasks inside an async generator require holding a task group open
  across `yield`, a known anyio/asyncgen footgun, and `asyncio.create_task`
  would break the trio test matrix this repo runs.
- The cost of inline is one verify per sentence (~tens of ms on CPU for
  deberta-v3-base against ≤ a handful of blocks) serialized with generation —
  a few hundred ms across a typical answer, versus the ~4s the buffering costs
  today.
- Running verification in a worker thread is itself a concurrency fix: the
  buffered implementation called `verify()` **synchronously on the event
  loop**, stalling all concurrent streams during NLI inference.

Revisit trigger for pipelining: if the B3 load re-measurement misses the
ADR-0017 SLA and per-sentence verification (not provider latency) is the
dominant term, implement the ordered-pipeline variant.

### 4. Failure policy: `stream_verification_policy` (config, default `retract`)

- **`retract`** (default): on the first unsupported sentence, stop generation,
  emit `retraction {reason: "verification_failed"}` **only if** token events
  were already emitted, then `final {status: "not_enough_evidence"}` with the
  standard message. Clients must replace any displayed partial text. The user
  may briefly see verified-then-retracted text; every displayed token was
  individually verified, but a truncated argument can mislead, so the default
  retracts fully.
- **`truncate`**: stop at the last verified sentence and emit
  `final {status: "answered", truncated: true}` whose `answer_text` is exactly
  the emitted text. Off by default; exists for UX experiments.

### 5. SSE event grammar (supersedes the buffered grammar)

| Outcome | Sequence |
|---|---|
| Answered | `retrieval` → `token`+ → `verification {status: supported}` → `citations` → `final {status: answered}` → `done` |
| No evidence | `retrieval` → `final {status: not_enough_evidence}` → `done` |
| First sentence fails (nothing emitted) | `retrieval` → `verification {status: unsupported}` → `final {status: not_enough_evidence}` → `done` |
| Mid-stream failure, `retract` | `retrieval` → `token`+ → `verification {status: unsupported}` → `retraction` → `final {status: not_enough_evidence}` → `done` |
| Mid-stream failure, `truncate` | `retrieval` → `token`+ → `verification {status: unsupported}` → `citations` → `final {status: answered, truncated: true}` → `done` |

Changes vs the buffered grammar: `token` events now *precede* the aggregate
`verification` event (verification per sentence happens before each emission;
the single `verification` event reports the aggregate at end of stream);
`retraction` is new; `final` gains an optional `truncated` flag. A `token`
event's `text` is one verified sentence (sentence-granular chunks, not raw LLM
tokens — raw token granularity is impossible under sentence-level verification
by definition). Invariant unchanged and now finer-grained: **no `token` event
is ever emitted before its sentence passes verification.**

### 6. Verifier instance caching (load-bearing fix)

`_build_chat_service` constructed a **new `NliAnswerVerifier` per request**,
which loads cross-encoder weights from disk on every chat call in production —
several seconds of TTFT the load tests never saw (they injected a warm
verifier into a single service). NLI verifier instances are now process-cached
keyed by their configuration. Without this, sentence-incremental streaming
would still miss the SLA in production on the first sentence.

### 7. Blocking `/chat` unchanged

The blocking path keeps whole-answer verification with `unsupported_ratio`
aggregation, per ADR-0016.

## Consequences

### Positive

- TTFT returns to ~LLM-first-sentence latency (~1–2s expected) from ~6s.
- Evidence discipline strengthens: per-sentence gating; a detected-contradicted
  sentence is never emitted (the buffered path emitted whole answers containing
  up to 20% unsupported sentences).
- Event loop no longer blocks during verification under concurrent load.
- Per-request model reload in production is gone.

### Negative

- Streaming and blocking can disagree on borderline answers (streaming
  stricter). Documented; acceptable.
- Clients must handle `retraction` (replace displayed text). Verified text may
  be displayed and then retracted — a UX cost the `truncate` policy can trade
  against.
- Sentence-granular emission means coarser visual streaming than raw tokens.
- One verify call per sentence adds ~tens of ms each, serialized with
  generation (inline v1).

## Alternatives considered

- **Keep full-answer buffering** — rejected: measured 5.97s P50 TTFT; SLA
  failing; the latency grows with answer length.
- **Stream unverified with a disclaimer, verify async** (ADR-0008's original
  async-quality-path reading) — rejected: violates invariant #5 as hardened on
  2026-05-23; unsupported text would reach clients.
- **Pipelined verification (ordered queue)** — deferred, not rejected: see §3
  revisit trigger.
- **Paragraph-granular verification** — rejected: coarser TTFT for no accuracy
  gain; the verifier is sentence-native.
- **Tolerate `unsupported_ratio` in streaming by emitting flagged sentences** —
  rejected: knowingly emitting a contradicted sentence is indefensible under
  invariant #5.

## References

- `docs/uber-rag/adr/0017-streaming-latency-sla.md` — SLA + failing-by-design status
- `docs/uber-rag/adr/0016-faithfulness-metric-selection.md` — scoring modes, ratio semantics
- `docs/uber-rag/adr/0008-fast-hot-path-async-quality.md` — latency architecture
- `tests/eval/reports/load_post_buffering.json` — buffered-path measurement
- `docs/superpowers/plans/2026-06-10-sota-master-plan.md` § Phase B
- Architecture invariant #5 (`AGENTS.md`): evidence discipline

## Revisit triggers

- B3 load re-measurement still misses ADR-0017 SLA with verification (not
  provider latency) dominant → implement pipelined ordered-queue variant.
- A streaming-capable grounding verifier (master plan Phase D) changes the
  per-sentence verification cost profile.
- Client/UX data shows retraction is worse than truncation in practice →
  flip the default policy (config already exists).
