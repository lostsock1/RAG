# Phase 3 Entry Research Note

Date: 2026-05-20
Phase: Phase 3 — Search MVP entry gate
Status: Complete

## Question

Can Uber-RAG proceed into Phase 3 Search MVP without reopening the current retrieval stack, and what changed in Qdrant, OpenSearch, BGE-M3, or fusion guidance that should affect the first implementation slice?

## Scope checked

- Qdrant hybrid retrieval, filtering, text search, multitenancy, and strict-mode behavior
- OpenSearch hybrid search, BM25, phrase search, bool filters, and document-level security
- BGE-M3 current model-card / repo posture and possible successor signals
- RRF vs DBSF as the first fusion choice for the Search MVP

## Method

- Reviewed current project memory and the current thin `/search` seam.
- Used source-backed deep research focused on official docs, official repos, and model cards.
- Kept the phase goal fixed: ranked, ACL-filtered, citation-bound chunk retrieval through the public API.

## Findings

### 1. Qdrant remains viable for vector retrieval, but not as the lexical system of record

Qdrant now supports hybrid fusion directly in the Query API and documents both **RRF** and **DBSF**.

Important implementation notes:

- payload filters are strong enough for ACL and tenant enforcement
- multitenancy and shard-routing features exist if tenant volume grows
- strict mode can reject retrieval on unindexed filtered fields
- text and phrase search exist, but they are filter-oriented and are not a substitute for OpenSearch BM25 ranking

Conclusion:

- keep Qdrant as the dense + sparse vector retrieval backend
- do not collapse lexical retrieval into Qdrant for Phase 3

### 2. OpenSearch remains the lexical system of record

OpenSearch remains the stronger lexical engine for the Search MVP.

Why:

- BM25 is still the default keyword relevance path
- `match_phrase` supports exact ordered phrase queries with `slop`
- `bool.filter` is non-scoring and cache-friendly for ACL constraints
- document-level security exists as defense in depth
- hybrid search is first-class and now has built-in RRF support in current docs

Important ACL note:

- use top-level hybrid or bool filters for ACL gating
- do **not** rely on `post_filter` for ACL enforcement in the MVP because it is applied after retrieval and can distort hybrid scoring behavior

### 3. BGE-M3 is still valid; no hard replacement is required

No official deprecation signal was found for **BGE-M3**.

It remains a good fit because one model can still provide:

- dense embeddings
- sparse lexical weights
- multivector outputs for later phases

There is an official stronger multilingual dense alternative in the same family: **BAAI/bge-multilingual-gemma2**.

However:

- it is not a clean drop-in replacement for the full BGE-M3 dense+sparse+multivector story
- it should be treated as a candidate only if the project later decides to prioritize dense multilingual quality over the single-model multifunction design

### 4. Fusion choice: start with RRF, defer DBSF experiments

**Recommendation: start Phase 3 with RRF.**

Why RRF is the better first implementation:

- it is rank-based, so it is more stable across incompatible score scales from BM25, phrase, dense, and sparse retrieval
- it is portable across both backends in this stack
- it is easier to reason about under ACL-filtered candidate pools, where score distributions can shift by tenant and permission scope

Why DBSF should wait:

- it is currently documented on Qdrant, not the full two-backend stack
- it depends on per-query score-distribution normalization, which is a weaker first fit for a still-evolving MVP pipeline

## Entry-gate conclusion

**Phase 3 status: Go.**

No hard blocker was found for starting Search MVP implementation with the current stack assumptions, provided the project keeps the backend split explicit:

- **OpenSearch** for lexical / phrase / BM25 retrieval
- **Qdrant** for dense + sparse vector retrieval
- **RRF** as the first fusion strategy

## Required implementation notes

- Require indexed ACL fields on both retrieval backends before relying on filters in production.
- Treat OpenSearch DLS as defense in depth, not as a substitute for application-level ACL filters.
- Keep DBSF and weighted fusion as later relevance-tuning work after the project has judgment data.
- Record version-sensitive capability notes in `STACK_REFERENCES.md` before implementation begins.

## Sources

Access date for all external sources: 2026-05-20.

- Qdrant hybrid queries — https://qdrant.tech/documentation/concepts/hybrid-queries
- Qdrant filtering — https://qdrant.tech/documentation/search/filtering/
- Qdrant indexing — https://qdrant.tech/documentation/concepts/indexing
- Qdrant multitenancy — https://qdrant.tech/documentation/manage-data/multitenancy/
- Qdrant administration / strict mode — https://qdrant.tech/documentation/guides/administration
- Qdrant text search — https://qdrant.tech/documentation/guides/text-search/
- OpenSearch hybrid search — https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/index/
- OpenSearch hybrid query — https://docs.opensearch.org/latest/query-dsl/compound/hybrid/
- OpenSearch score ranker processor — https://docs.opensearch.org/latest/search-plugins/search-pipelines/score-ranker-processor/
- OpenSearch normalization processor — https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/
- OpenSearch hybrid post-filtering — https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/post-filtering/
- OpenSearch bool query — https://docs.opensearch.org/latest/query-dsl/compound/bool/
- OpenSearch match phrase query — https://docs.opensearch.org/latest/query-dsl/full-text/match-phrase/
- OpenSearch keyword search — https://docs.opensearch.org/latest/search-plugins/keyword-search/
- OpenSearch document-level security — https://docs.opensearch.org/latest/security/access-control/document-level-security/
- BGE-M3 model card — https://huggingface.co/BAAI/bge-m3
- FlagEmbedding repo — https://github.com/FlagOpen/FlagEmbedding
- BGE-M3 research folder — https://github.com/FlagOpen/FlagEmbedding/tree/master/research/BGE_M3
- BGE-Multilingual-Gemma2 model card — https://huggingface.co/BAAI/bge-multilingual-gemma2
