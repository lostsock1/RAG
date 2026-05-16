# ADR-0008: Fast Hot Path, Async Quality Path

Status: Accepted
Date: 2026-05-15

## Context

Uber-RAG is being designed against a user-facing `/chat` latency target of approximately **2 seconds** for normal queries.

The current retrieval pipeline shape is quality-oriented:

```text
query router
  -> exact / phrase / BM25
  -> dense
  -> sparse
  -> fusion
  -> parent-child expansion
  -> reranking
  -> answer generation
  -> sentence-level evidence verification
```

This shape is correct in principle, but if every stage runs synchronously on every query, the system will be slow by design. The main risk is not retrieval itself; it is the cumulative cost of:

- running all retrieval branches even for simple exact-match queries
- reranking too many candidates
- expanding parent context too early
- forcing sentence-level verification into the blocking user path
- using one expensive path for all query types

The user stated the latency priority clearly: **speed first now, with the option to earn higher quality later**. The project still requires evidence discipline and source-bound answers. So the design problem is not “drop quality,” but “decide which quality steps belong in the synchronous path vs the asynchronous path.”

## Decision

Adopt a **two-path architecture**:

1. **Hot path (blocking, user-visible)**
   - query routing
   - parallel candidate retrieval
   - fusion
   - conditional reranking
   - tight context construction
   - answer generation
   - immediate response with citations

2. **Quality path (non-blocking, asynchronous)**
   - sentence-level evidence verification
   - deeper audit enrichment
   - optional post-response correction/flagging

### Routing policy

Every query must be routed into a latency tier.

#### Tier 1 — Exact fast lane
Used for IDs, quoted phrases, filenames, page references, rare terms.

- lexical / phrase / exact retrieval first
- skip dense+sparse if lexical confidence is sufficient
- skip reranker by default
- skip parent expansion by default
- no blocking verifier

Target: **sub-second to ~2 seconds** end-to-end.

#### Tier 2 — Semantic normal path
Used for concept explanations and ordinary knowledge questions.

- lexical + dense + sparse in parallel
- fusion
- rerank only top-N fused candidates
- minimal parent expansion only if required by context builder
- no blocking verifier

Target: **~2 seconds typical, higher only when justified**.

#### Tier 3 — Synthesis path
Used for chapter-level synthesis, cross-corpus comparison, and other complex questions.

- lexical + dense + sparse in parallel
- fusion
- rerank a slightly larger top-N set
- parent expansion allowed
- no blocking verifier

Target: best effort. May exceed 2 seconds, but this is the exception path, not the default path.

### Synchronous-path rules

- **No sentence-level verifier in the blocking user path.**
- **No reranking on exact-route queries by default.**
- **No parent expansion on exact-route queries by default.**
- **Every expensive stage must be route-gated, not globally mandatory.**
- **Citations remain mandatory in the hot path.** The response is still evidence-bound even when verification is deferred.

### Asynchronous quality-path rules

After a response is returned:

- run the sentence-level verifier against the final answer and cited evidence
- record the verifier result in audit / telemetry
- if unsupported claims are found, attach a quality flag to the answer record and citation view
- do not silently alter the already-returned answer in MVP; correction UX is a later product decision

## Consequences

### Positive

- Aligns the architecture with the explicit 2-second UX target.
- Prevents the system from becoming slow by design before implementation begins.
- Preserves the ability to improve quality later because reranking, verification, and expansion remain modular and switchable.
- Forces the router to matter, which is correct for a heterogeneous RAG system serving exact lookups and synthesis queries.
- Makes performance tuning measurable: every expensive stage now has a route, a budget, and an off-switch.

### Negative

- Some unsupported claims may be shown briefly before async verification flags them.
- Exact-route queries may occasionally miss a benefit that reranking would have added.
- The system becomes more operationally complex because it now has both a blocking path and a background quality path.
- Product/UI work will eventually need a way to expose verifier outcomes cleanly.

## Alternatives considered

- **Full quality-first synchronous pipeline** — rejected. This conflicts with the 2-second target and makes the product feel slow by design.
- **No verifier at all** — rejected. Violates evidence discipline and weakens the project’s commercial trust goal.
- **Always rerank, but move only the verifier async** — rejected as the default. Better than a fully synchronous pipeline, but still too expensive for exact-match and page-reference queries.
- **One-path architecture with only implementation-level tuning later** — rejected. If every request is architecturally forced through the same heavy path, implementation tuning will not rescue the UX.

## References

- Internal: `/Users/djesys/.config/opencode/agents/RAG/_shared.md` — retrieval pipeline and evidence discipline
- Internal: `docs/uber-rag/ARCHITECTURE.md`
- Internal: `docs/uber-rag/RETRIEVAL_QUALITY.md`
- Internal: `docs/uber-rag/EVALUATION_HARNESS.md`
- Internal: `docs/uber-rag/adr/0004-llm-adapter-and-provider.md`

## Revisit triggers

Reopen this ADR if any of the following happens:

- measured user-visible `/chat` latency is consistently above target even on Tier 1 exact-route queries
- async verifier flags more than 10% of answers as materially unsupported on the held-out eval set
- reranker removal on exact-route queries causes unacceptable citation or answer-quality regressions
- product requirements change from “~2 seconds target” to a slower quality-first interaction model
- local model serving becomes fast enough that some currently async quality steps can move back into the hot path without violating latency targets
