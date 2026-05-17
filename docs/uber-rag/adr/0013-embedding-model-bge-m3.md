# ADR-0013: Embedding Model — BGE-M3 Dense + Sparse

Status: Proposed
Date: 2026-05-17

## Context

The ingestion pipeline now has chunking (ADR-0012) and stub embed/index stages wired. The next step is a real embedding adapter. This ADR formalizes the embedding model selection and configuration that was assumed in ADR-0004 (default stack) and ADR-0012 (chunking constraints).

This decision determines:

1. **Model** — which embedding model produces dense and sparse vectors.
2. **Output dimensions** — dense vector dimensionality and sparse vocabulary size.
3. **Batch size** — how many chunks are embedded per forward pass.
4. **Normalization** — whether dense vectors are L2-normalized before indexing.
5. **Adapter interface** — how the model is wrapped behind the `Embedder` protocol.

### Constraints

- **BGE-M3** was selected in the default stack (ADR-0004) as the embedding model. It produces dense, sparse (lexical), and ColBERT (multi-vector) outputs in a single forward pass.
- **Qdrant** supports named sparse vectors natively (since 1.7+). Dense vectors use cosine similarity; sparse vectors use dot product.
- **OpenSearch** handles BM25/lexical search separately — the sparse vectors from BGE-M3 are for Qdrant's hybrid search, not OpenSearch.
- **Chunk size** is 128–512 tokens for leaf chunks (ADR-0012). BGE-M3's recommended `max_length=512` aligns with this ceiling.
- **No local GPU** — the model must run on CPU for development, with GPU acceleration optional for production.
- **Air-gapped deployment** — the model must be downloadable once and cached locally.

### Research basis

- BGE-M3 model card: https://huggingface.co/BAAI/bge-m3
- FlagEmbedding library: https://github.com/FlagOpen/FlagEmbedding
- BGE-M3 paper: Chen et al., "BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation" (2024)

## Decision

### Model: BAAI/bge-m3

Use `BAAI/bge-m3` via the `FlagEmbedding` library's `BGEM3FlagModel` class.

**Rationale:**
- Single model produces dense (1024-dim), sparse (lexical BM25-compatible), and ColBERT outputs.
- Multilingual: 100+ languages including German and Portuguese (matching the eval set).
- State-of-the-art on MTEB multilingual benchmarks at time of selection.
- `FlagEmbedding` provides a clean Python API with batched inference.
- Model size (~2.2 GB) is manageable for CPU inference at development scale.

### Configuration

| Parameter | Value | Rationale |
|---|---|---|
| Dense dimension | 1024 | BGE-M3 default output |
| Sparse output | Enabled | For Qdrant hybrid search |
| ColBERT output | Disabled (initially) | Deferred to Phase 7 (advanced retrieval) |
| Max length | 512 tokens | Aligns with ADR-0012 leaf chunk ceiling |
| Batch size | 12 (CPU) / 32 (GPU) | Conservative for CPU; larger for GPU |
| Normalization | L2 normalize dense vectors | Required for cosine similarity in Qdrant |
| Device | `cpu` default, `cuda` when available | Development on CPU, production on GPU |

### Adapter: `BgeM3Embedder`

Implement `BgeM3Embedder` behind the existing `Embedder` protocol:

```python
class BgeM3Embedder:
    def __init__(self, model_name: str = "BAAI/bge-m3", device: str = "cpu", batch_size: int = 12): ...
    def embed(self, *, chunk_ids: list[UUID], texts: list[str]) -> list[EmbeddingResult]: ...
```

- Lazy model loading: the model is loaded on first `embed()` call, not at import time.
- Batched inference: texts are processed in batches of `batch_size`.
- Output mapping: dense → `DenseVector(values=..., dimension=1024)`, sparse → `SparseVector(indices=..., values=...)`.

### Sparse vector format

BGE-M3 sparse output is a dict mapping token strings to float weights. The `SparseVector` schema stores integer indices and float values. The adapter will:

1. Build a vocabulary mapping from token strings to integer indices (using a hash of the token string for determinism).
2. Sort by index for Qdrant compatibility.
3. Store in `SparseVector(indices=[...], values=[...])`.

## Alternatives considered

1. **sentence-transformers** — also supports BGE-M3 but doesn't expose sparse/ColBERT outputs as cleanly as FlagEmbedding. Would require custom pooling logic.
2. **OpenAI embeddings** — API-only, not air-gapped compatible. Dense-only, no sparse output.
3. **E5-mistral-7b** — higher quality but 7B parameters, too large for CPU inference. Not multilingual.
4. **Cohere embed-v3** — API-only, not air-gapped compatible.

## Consequences

- **Positive:** Single model for dense + sparse, multilingual, air-gapped compatible, well-supported.
- **Positive:** ColBERT output available for future Phase 7 advanced retrieval without model change.
- **Negative:** 2.2 GB model download on first use. Need caching strategy for air-gapped deployment.
- **Negative:** CPU inference is slow (~50–100 ms per chunk on M-series Mac). GPU recommended for production.
- **Negative:** Sparse vector vocabulary is not fixed — different texts produce different token sets. Qdrant handles this natively but it complicates debugging.

## Open questions

- ColBERT enablement timing — defer to Phase 7 or enable earlier for experimentation?
- Sparse vocabulary hashing — use Python `hash()` (non-deterministic across runs) or a stable hash like `xxhash`? Decision: use `hashlib.sha256(token).hexdigest()` truncated to int64 for determinism.
