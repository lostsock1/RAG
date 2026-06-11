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

### Enablement measurement (2026-06-11) — production default stays `disabled`

The selection above was never the production *runtime* default
(`reranker_backend="disabled"`, stub reranker). Under the 2026-06-11 models
freeze (CPU-only VPS, API generation, no GPU), enabling the accepted model
was the one in-freeze ranking lever, so it was measured as an eval arm
(`tests/eval/test_retrieval_reranker_arm.py`; 60 questions, C5 corpus, E1
expansion ON, candidates=20, dev-Mac CPU; report
`tests/eval/reports/retrieval_reranker_arm.json`) against a decision rule
frozen before measurement: flip iff (MRR@10 or nDCG@10 lift ≥ +0.02 AND
recall@10 drop ≤ 0.02) AND mean overhead ≤ 1000 ms/query.

- **Quality — below the bar.** MRR@10 0.9270 → 0.9403 (+0.0132), nDCG@10
  0.9440 → 0.9554 (+0.0109); recall@10 unchanged at 1.000 (recall@5
  0.9833 → 1.000). Per-question: two rank-4 questions fixed to rank 1
  (h04, h16), two nudged up (h29, n12), two previously-perfect regressed
  to rank 2 (h12, h19) — net positive but sub-significance on the
  topically-distinct C5 corpus (its recorded caveat applies).
- **Latency — fails decisively.** Mean overhead **+2436 ms/query**
  (157 → 2593 ms; P95 4084 ms) vs the 1000 ms bar, measured on hardware
  *optimistic* relative to the production VPS. Stacked on the measured
  3.11 s P50 first-verified-token, this breaks the ADR-0017 5 s budget.

**Outcome: no flip — `reranker_backend` default stays `disabled`.** The
model selection itself is unaffected; v2-m3 remains the accepted,
config-selectable model. Enablement reopen paths: (a) the harder distractor
corpus (Phase E backlog) may lift quality past the bar, but latency fails
independently of corpus difficulty; (b) ONNX-optimized CPU serving (DeepEye
note above: ~400–530 ms / 20 pairs, ≈5× faster than the eager-PyTorch
number measured here) and/or a smaller rerank candidate count could pass
the latency bar — same model, freeze-compatible in principle, unscheduled.

Implementation note (same date): `BgeRerankerV2M3` was reimplemented on
plain transformers (`AutoModelForSequenceClassification` +
`AutoTokenizer`, official model-card scoring) because FlagEmbedding 1.4.0's
reranker path calls `tokenizer.prepare_for_model`, which transformers 5.x
removed for slow tokenizers — the previous implementation crashed on first
real rerank under the pinned stack (transformers 5.8.1). Class interface
and config knobs are unchanged; a regression guard in
`apps/api/app/tests/unit/test_bge_reranker.py` keeps FlagEmbedding out of
the module.

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
