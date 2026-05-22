# ADR-0014: Phase 4 Reranker Selection — Reconfirm `bge-reranker-v2-m3`

Status: Accepted
Date: 2026-05-21

## Context

Phase 4 was blocked on the reranker stack row. The open candidates were:

1. `BAAI/bge-reranker-v2-m3`
2. `BAAI/bge-reranker-v2-gemma`
3. `BAAI/bge-reranker-v2-minicpm-layerwise`

Uber-RAG needs a reranker that fits the current Phase 4 constraints:

- user-facing hot-path latency discipline from ADR-0008
- exact-match routes must be able to bypass reranking
- no local GPU is available during current Phase 4 development
- multilingual retrieval quality matters
- operational and security friction matters because this is part of a user-facing, ACL-aware system

Current BAAI guidance now says `bge-reranker-v2-gemma` and `bge-reranker-v2-minicpm-layerwise` are better-performance options, while `bge-reranker-v2-m3` remains the efficiency-oriented choice. That created real supersession pressure on the previous default assumption and forced a decision review before Phase 4 could begin.

## Decision

Reconfirm **`BAAI/bge-reranker-v2-m3`** as the default Uber-RAG reranker for **Phase 4**.

This is an explicit stack decision, not a silent carry-forward.

## Rationale

### Why `bge-reranker-v2-m3`

- It is the best fit for current hot-path latency constraints.
- It has the lowest operational complexity of the three candidates.
- Its official loading path uses the standard sequence-classification flow without `trust_remote_code`.
- It is a better fit for no-GPU development than the larger decoder-style rerankers.
- It preserves a clean BGE-family alignment with the accepted `BGE-M3` embedding row.

### Why not `bge-reranker-v2-gemma` as the default

- BAAI positions it as a stronger-performance candidate, so it remains a credible later upgrade path.
- But its larger inference footprint and decoder-style reranker path are a worse fit for the current latency-oriented, no-GPU Phase 4 start.
- It is better treated as the **first reopen candidate** if `v2-m3` misses quality targets.

### Why not `bge-reranker-v2-minicpm-layerwise` as the default

- It has potential quality and tunable latency upside through cutoff layers.
- But the official usage path requires `trust_remote_code=True`.
- For Uber-RAG's current security and operational posture, that is too much friction for the default Phase 4 row when a viable standard-loading alternative exists.
- Treat it as a later experiment only if the team explicitly accepts pinned-revision custom-code execution in a dedicated inference boundary.

## Consequences

### Positive

- Phase 4 is unblocked.
- The default reranker matches the current architecture and latency budget better than the larger alternatives.
- The implementation can start with a model-swappable `Reranker` interface while still using a low-friction default.
- Security posture stays simpler than the MiniCPM layerwise path.

### Negative

- The project may leave some quality on the table relative to `v2-gemma` or `v2-minicpm-layerwise`.
- A later reranker bake-off may still justify reopening this ADR.

## Reopen triggers

Reopen this ADR if any of the following happens:

1. **Quality miss:** `bge-reranker-v2-m3` misses the project's Phase 4 relevance or evidence-grounding targets, and another candidate shows a material improvement.
2. **Measured gain threshold:** `v2-gemma` or `v2-minicpm-layerwise` shows at least +3.0 nDCG@10, +2.0 MRR@10, or +2 percentage points on answer-supported / evidence-grounded success over `v2-m3` on the Uber-RAG eval set.
3. **Truncation pressure:** more than 15% of reranked query-passage pairs are materially truncated under the effective `v2-m3` passage budget on representative traffic or eval queries.
4. **Serving conditions improve:** a dedicated GPU reranker service becomes available and keeps gated-route rerank latency within 2x of `v2-m3` for the same top-N candidate count.
5. **Language mix narrows:** production traffic becomes predominantly English + Chinese, making the MiniCPM layerwise tradeoff more attractive.
6. **Security posture changes:** the team explicitly approves pinned-revision custom-code execution for model loading, which is a prerequisite for reconsidering `v2-minicpm-layerwise`.

### DeepEye verification note (2026-05-21)

Independent DeepEye research unanimously confirmed this decision. Key new data:

- `bge-reranker-v2-gemma` is **deprecated by HuggingFace Inference** (HF Discussion #8). This weakens it as the first reopen candidate. If quality targets are missed, `bge-reranker-v2-minicpm-layerwise` (with explicit `trust_remote_code` acceptance) or `bge-reranker-v2.5-gemma2-lightweight` (GPU-era, 9B params, BEIR 63.1) are more credible future paths.
- CPU latency for v2-m3 with ONNX optimization: ~400-530ms for 20 candidate pairs, 4x under the 2s budget.
- MIRACL multilingual gap between v2-m3 and v2-gemma is only +0.6 nDCG@10, negligible for Uber-RAG trilingual corpus.
- `trust_remote_code` risk is worse than originally documented: CVE-2026-27893 (HIGH 8.8), demonstrated RCE PoCs, and a 2026 arxiv empirical study confirming arbitrary code execution capability.

## References

Access date for all external sources: 2026-05-21.

- BGE reranker docs — https://bge-model.com/tutorial/5_Reranking/5.2.html
- `BAAI/bge-reranker-v2-m3` model card — https://huggingface.co/BAAI/bge-reranker-v2-m3/raw/main/README.md
- `BAAI/bge-reranker-v2-gemma` model card — https://huggingface.co/BAAI/bge-reranker-v2-gemma/raw/main/README.md
- `BAAI/bge-reranker-v2-minicpm-layerwise` model card — https://huggingface.co/BAAI/bge-reranker-v2-minicpm-layerwise/raw/main/README.md
- Hugging Face Transformers security policy — https://github.com/huggingface/transformers/blob/main/SECURITY.md
- Google Gemma 2B model card — https://huggingface.co/google/gemma-2b
- OpenBMB MiniCPM-2B-DPO-BF16 model card — https://huggingface.co/openbmb/MiniCPM-2B-dpo-bf16/raw/main/README.md
- Internal research note — `docs/uber-rag/research/2026-05-21-phase-4-entry.md`
- Internal architecture constraint — `docs/uber-rag/adr/0008-fast-hot-path-async-quality.md`
