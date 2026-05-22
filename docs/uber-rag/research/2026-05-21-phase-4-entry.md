# Phase 4 Entry Research Note

Date: 2026-05-21
Phase: Phase 4 — Reranking, generation, verification entry gate
Status: Complete

## Bottom Line

Uber-RAG can begin Phase 4 implementation work. The reranker row is now **closed for Phase 4**: `BAAI/bge-reranker-v2-m3` is explicitly reconfirmed as the default because it best fits current hot-path latency, no-GPU development, and lower-friction operational/security constraints. `bge-reranker-v2-gemma` remains the first reopen candidate if quality targets are missed. `bge-reranker-v2-minicpm-layerwise` is not the default because its `trust_remote_code` path adds avoidable friction for the current phase.

## Question

Can Uber-RAG enter Phase 4 with the current reranking / generation / verification assumptions unchanged, and what stack rows now require a reopened decision?

## Sources

- BGE-M3 model card: https://huggingface.co/BAAI/bge-m3
  - Accessed: 2026-05-21
  - Version: current model card
  - Tier: 1
  - Reliability: official vendor model card
- BGE reranker v2 m3 model card: https://huggingface.co/BAAI/bge-reranker-v2-m3
  - Accessed: 2026-05-21
  - Version: current model card
  - Tier: 1
  - Reliability: official vendor model card
- BGE reranker v2 gemma model card: https://huggingface.co/BAAI/bge-reranker-v2-gemma
  - Accessed: 2026-05-21
  - Version: current model card
  - Tier: 1
  - Reliability: official vendor model card
- BGE reranker v2 MiniCPM layerwise model card: https://huggingface.co/BAAI/bge-reranker-v2-minicpm-layerwise/raw/main/README.md
  - Accessed: 2026-05-21
  - Version: current model card
  - Tier: 1
  - Reliability: official vendor model card
- Hugging Face Text Generation Inference docs: https://huggingface.co/docs/text-generation-inference
  - Accessed: 2026-05-21
  - Version: current docs
  - Tier: 1
  - Reliability: official docs
- Hugging Face Transformers security policy: https://github.com/huggingface/transformers/blob/main/SECURITY.md
  - Accessed: 2026-05-21
  - Version: current repo file
  - Tier: 1
  - Reliability: official repository policy
- SGLang docs: https://docs.sglang.ai/
  - Accessed: 2026-05-21
  - Version: current docs
  - Tier: 1
  - Reliability: official docs
- Llama 3.3 70B Instruct model card: https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct
  - Accessed: 2026-05-21
  - Version: current model card
  - Tier: 1
  - Reliability: official vendor model card
- Awesome-AI-Memory: https://github.com/IAAR-Shanghai/Awesome-AI-Memory
  - Accessed: 2026-05-21
  - Version: current repo state
  - Tier: 1
  - Reliability: official curated repository
- From Lossy to Verified: A Provenance-Aware Tiered Memory for Agents: https://arxiv.org/pdf/2602.17913v1.pdf
  - Accessed: 2026-05-21
  - Version: arXiv v1
  - Tier: 1
  - Reliability: primary paper
- Beyond RAG for Agent Memory: Retrieval by Decoupling and Aggregation: https://arxiv.org/pdf/2602.02007
  - Accessed: 2026-05-21
  - Version: arXiv current
  - Tier: 1
  - Reliability: primary paper
- TraceMem: Weaving Narrative Memory Schemata from User Conversational Traces: https://arxiv.org/pdf/2602.09712
  - Accessed: 2026-05-21
  - Version: arXiv current
  - Tier: 1
  - Reliability: primary paper

## Findings

### 1. Embeddings remain stable enough to proceed

`BAAI/bge-m3` still fits Uber-RAG unusually well because one model provides dense, sparse, and multivector retrieval support; its own card still recommends a **hybrid retrieval + re-ranking** pipeline. No official deprecation or supersession signal was found. This confirms the current BGE-M3 assumption for Phase 4.

### 2. The reranker row had material supersession pressure and is now resolved

The current `bge-reranker-v2-m3` card still presents the model as multilingual, lightweight, and efficient. However, BAAI's current reranker guidance now says:

- use `bge-reranker-v2-m3` for efficiency
- use `bge-reranker-v2-gemma` or `bge-reranker-v2-minicpm-layerwise` for better performance

That was enough to reopen the reranker row as a decision. After comparative review, Uber-RAG reconfirms `bge-reranker-v2-m3` as the Phase 4 default because it is the best fit for the current latency-oriented, no-local-GPU phase constraints.

### 3. Current Phase 4 LLM direction still holds

`meta-llama/Llama-3.3-70B-Instruct` remains a defensible Phase 0–4 testing default: 128k context, 8 supported languages, tool-use support, and strong general instruction benchmarks. This remains consistent with ADR-0004's no-local-GPU constraint and ppq.ai-based testing path.

### 4. Self-hosted runtime revisit has sharpened, but not for this phase

Current API-based testing remains the right path because no local GPU is available. For the later self-hosted runtime decision, the future comparison has become clearer:

- TGI is now explicitly in maintenance mode and recommends downstream engines such as vLLM, SGLang, and llama.cpp.
- SGLang now presents itself as a high-performance OpenAI-compatible serving framework with broad hardware support.

This does not reopen ADR-0004 for Phase 4, but it does sharpen the later local-runtime ADR question from “vLLM vs llama.cpp” into “SGLang vs vLLM, with llama.cpp reserved for lower-memory paths.”

### 5. Verification architecture remains directionally correct

Recent memory/provenance papers continue to support Uber-RAG's evidence discipline rather than weaken it. The strongest pattern is not “cite less,” but “track provenance more explicitly” with a distinct evidence aggregation / verification layer. That supports keeping sentence-level verification and clear not-found behavior as Phase 4 requirements.

## Implementation impact

- Phase 4 can proceed with a modular `Reranker` interface, context builder, LLM adapter, and verifier seams.
- Treat `bge-reranker-v2-m3` as the accepted Phase 4 default, not merely a carry-forward assumption.
- Keep the adapter model-swappable because `bge-reranker-v2-gemma` remains a credible reopen candidate if measured quality targets are missed.
- Update `STACK_REFERENCES.md` and `PROJECT_STATE.md` to record:
  - reranker supersession pressure
  - current-phase reconfirmation of BGE-M3 and Llama 3.3 via ppq.ai
  - future runtime revisit signal: SGLang vs vLLM

## Open questions

- How much answer-quality gain do `bge-reranker-v2-gemma` or `bge-reranker-v2-minicpm-layerwise` buy on Uber-RAG's multilingual, ACL-filtered retrieval workload?
- Does the quality gain survive the latency budget imposed by ADR-0008's hot path?
- Is `trust_remote_code` on the MiniCPM layerwise path acceptable for this project, or should it be treated as a security/operational negative?
- What measured Phase 4 eval thresholds should automatically trigger a reranker reopen beyond the ADR defaults?

## DeepEye independent verification (2026-05-21)

After ADR-0014 was accepted, `search/deepeye` was dispatched for independent verification. DeepEye returned a comprehensive report with 20+ sourced references. Key findings:

### DeepEye confirms ADR-0014

- **Default reconfirmed:** `bge-reranker-v2-m3` is the unanimous recommendation across all data points.
- **CPU latency validated:** ~400–530ms for 20 candidate pairs on CPU with ONNX optimization — 4× under the 2s budget.
- **Security strengthened:** `trust_remote_code` risk is worse than originally documented — CVE-2026-27893 (HIGH 8.8), demonstrated RCE PoCs, and a 2026 arxiv empirical study confirming arbitrary code execution.
- **Multilingual quality gap is minimal:** MIRACL 18-language benchmark shows v2-gemma beats v2-m3 by only +0.6 nDCG@10 — negligible for Uber-RAG's trilingual corpus.

### New findings not in original ADR-0014

1. **`bge-reranker-v2-gemma` is deprecated by HuggingFace Inference** (HF Discussion #8). This weakens it as a reopen candidate — a deprecated model is a poor long-term default.
2. **`bge-reranker-v2.5-gemma2-lightweight`** (9B params, Gemma 2 backbone) achieves BEIR mean 63.1 vs v2-m3's 55.36, but requires 9B-class hardware and is not CPU-viable. Potential Phase 5+ GPU-era candidate.
3. **Community ONNX export exists** (`newtechstudio/bge-reranker-v2-m3-onnx`) with TEI ORT backend — provides dynamic batching and reduces CPU latency to ~400ms.
4. **v2-gemma cannot be quantized** — FlagEmbedding silently ignores int8 quantization attempts (HF Discussion #3).
5. **v2-minicpm is "basically unusable" in production** via xinference (Issue #1377) and unsupported by TEI (Issue #297).

### Impact on ADR-0014

ADR-0014's decision is fully validated. The reopen triggers should be updated to note:
- `v2-gemma` deprecation weakens it as first reopen candidate; `v2-minicpm-layerwise` (with explicit `trust_remote_code` acceptance) or `v2.5-gemma2-lightweight` (GPU-era) are more credible future paths.
- ONNX export should be the recommended CPU deployment path for Phase 4.

### DeepEye sources (accessed 2026-05-21)

- BAAI official docs: https://bge-model.com/bge/bge_reranker_v2.html
- v2.5-gemma2-lightweight model card (BEIR/MIRACL tables): https://huggingface.co/BAAI/bge-reranker-v2.5-gemma2-lightweight
- Local AI Master 2026 survey: https://localaimaster.com/blog/reranking-cross-encoders-guide
- BSWEN CPU benchmarks: https://docs.bswen.com/blog/2026-02-25-best-reranker-models/
- Community ONNX export: https://huggingface.co/newtechstudio/bge-reranker-v2-m3-onnx
- Arxiv empirical study on trust_remote_code RCE: https://arxiv.org/html/2601.14163v1
- vLLM security advisory CVE-2026-27893: https://github.com/vllm-project/vllm/security/advisories/GHSA-7972-pg2x-xr59
- v2-gemma deprecation: https://huggingface.co/BAAI/bge-reranker-v2-gemma/discussions/8
- v2-gemma quantization failure: https://huggingface.co/BAAI/bge-reranker-v2-gemma/discussions/3
- xinference minicpm production failure: https://github.com/xorbitsai/inference/issues/1377
- TEI minicpm unsupported: https://github.com/huggingface/text-embeddings-inference/issues/297
- Open WebUI minicpm loading failure: https://github.com/open-webui/open-webui/issues/2137
- Pinecone v2-m3 endorsement: https://docs.pinecone.io/models/bge-reranker-v2-m3

## Research method note

Per `RESEARCH_PROTOCOL.md:85-97`, DeepEye is the preferred tool for multi-source comparative work like this reranker decision. The initial decision was closed from direct-source comparative review and formalized in ADR-0014. DeepEye was then dispatched for independent verification and unanimously confirmed the decision while surfacing new data (gemma deprecation, v2.5-gemma2-lightweight, ONNX deployment path, CVE details).
