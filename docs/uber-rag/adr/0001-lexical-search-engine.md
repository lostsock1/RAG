# ADR-0001: Lexical Search Engine — OpenSearch over Tantivy

Status: Accepted
Date: 2026-05-14

## Context

The retrieval pipeline requires a lexical (BM25, phrase, exact) backend alongside Qdrant for dense + sparse vector retrieval. `STACK_REFERENCES.md` lists two candidates:

- **OpenSearch** — production-proven, JVM, full HTTP/REST API, document-level security plugin, mature analyzer ecosystem, snapshots, multi-node clustering.
- **Tantivy** — Rust crate, embeddable, very fast, no built-in clustering, no security plugin, no admin UI, more glue code required.

The project is API-first, multi-tenant by design (Keycloak + Postgres RLS), ACL-aware at every retrieval layer, and targets commercial multi-user deployment. Air-gapped readiness is required. The corpus is multilingual (German, Portuguese, English).

Running two BM25 backends would be worse than picking one: split debugging effort, doubled index maintenance, complicated fusion scoring. This ADR closes the choice.

## Decision

Use **OpenSearch** as the lexical search engine.

The retrieval module wraps OpenSearch behind a `LexicalIndex` interface (see `RETRIEVAL_QUALITY.md`) so a future swap remains possible, but no second backend is supported in MVP.

## Consequences

### Positive

- Mature multilingual analyzers (German + Portuguese stemmers, ICU tokenization) match the corpus profile without custom tokenization work.
- Security plugin provides document-level security as a defense-in-depth layer behind Postgres RLS and Qdrant ACL filters (see `SECURITY_ACL.md` § Defense-in-depth).
- Snapshot/restore semantics fit the air-gapped artifact-promotion model cleanly.
- Operations team can use existing OpenSearch tooling (Dashboards, alerting, monitoring exporters).
- Cluster-ready when scale demands it — no migration needed later.

### Negative

- Heavy JVM footprint. Dev environment requires ~2 GB RAM minimum for a single-node OpenSearch instance.
- Operational complexity is higher than Tantivy. The team must learn cluster health, shard management, and index lifecycle policies.
- Slower cold start in CI than embedded Tantivy. Mitigate with a shared CI service container.
- Pins us to OpenSearch's roadmap (Apache 2.0 fork), not Elastic's. License is commercially clean.

## Alternatives considered

- **Tantivy** — rejected. Excellent embedded inside a single-process application; Uber-RAG is not that. We need document-level security, cluster scaling, and multilingual analyzers without building them ourselves.
- **Vespa** — rejected for this ADR. Technically attractive (vector + lexical + ranking in one engine) but operational and mental-model cost is high. Revisit if/when the project crosses ~50M chunks or needs learned ranking across modalities. Captured separately as a future-review item.
- **Elasticsearch (Elastic-licensed)** — rejected. SSPL / Elastic License v2 complicates commercial redistribution and air-gapped deployment.
- **MeiliSearch / Typesense** — rejected. Lexical features (custom analyzers, phrase queries with slop, exact-match scoring) are weaker than OpenSearch for textbook content where exact terminology matters.

## Revisit triggers

Reopen this ADR if any of the following happens:

- Corpus crosses 50M chunks AND P99 hybrid retrieval latency exceeds 500 ms — consider Vespa migration.
- OpenSearch's German or Portuguese analyzer quality underperforms alternatives on the corpus eval — investigate alternative analyzers or external tokenization before reopening.
- Air-gapped deployment ops report OpenSearch resource cost is unsustainable on customer hardware — reconsider Tantivy or external service.
- A second BM25 backend is requested for a specialized deployment (e.g., embedded Tantivy for a desktop client) — clarify whether that is an additional adapter or a replacement.

## References

- OpenSearch documentation — https://opensearch.org/docs/latest/ (accessed 2026-05-14)
- OpenSearch document-level security — https://opensearch.org/docs/latest/security/access-control/document-level-security/ (accessed 2026-05-14)
- Tantivy — https://github.com/quickwit-oss/tantivy (accessed 2026-05-14)
- Internal: `docs/uber-rag/STACK_REFERENCES.md` § Lexical Search
- Internal: `docs/uber-rag/RETRIEVAL_QUALITY.md`
- Internal: `docs/uber-rag/SECURITY_ACL.md` § Defense-in-depth layers
