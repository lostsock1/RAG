# ADR-0012: Chunking Strategy — Structure-Aware Parent-Child with Profile Routing

Status: Proposed
Date: 2026-05-17

## Context

Phase 2 ingestion has parsing, artifact persistence, and quality reporting wired. The next critical-path stage is **chunking**: splitting parsed documents into retrievable units that carry enough context for precise retrieval (small chunks) and coherent generation (parent context expansion).

This decision determines:

1. **Chunk granularity** — what size chunks are embedded and indexed.
2. **Parent-child hierarchy** — how small chunks map to larger context units for generation.
3. **Boundary strategy** — whether chunks respect document structure or use fixed-size splitting.
4. **Profile routing** — how book and loose-document profiles get different chunking treatment.

### Constraints

- **BGE-M3** is the embedding model (ADR-0004 stack). Its default `max_length=512` tokens; ceiling is 8192. The maintainer recommends 512-token chunks. Going beyond 512–1024 degrades dense retrieval quality.
- **Docling** is the parser (ADR-0011). Its `DoclingDocument` output provides heading hierarchy, item types (paragraph, table, formula, code, list), page numbers, bounding boxes, and a tree structure via JSON pointers. This is directly mappable to boundary-aware chunking.
- **Domain model** already defines a `chunks` table with `parent_id`, `heading_path`, `unit_type`, `chunk_index`, and a uniqueness constraint `(document_id, chunk_index, parser_version, embedding_model)` for idempotent reindexing.
- **Retrieval pipeline** (ARCHITECTURE.md) specifies parent-child expansion as a stage between fusion and reranking. The chunking strategy must produce the data this stage consumes.
- **Two document profiles** — book (deep hierarchy) and loose document (shallow hierarchy, rich metadata) — require different chunking treatment but share the same retrieval core.
- **Idempotency** — re-running chunking on the same parsed document must produce identical chunks (ADR-0002 rule 1).

### Research basis

Research note: `docs/uber-rag/research/2026-05-17-chunking-strategies.md` (358 lines, 15+ sources, 2026-05-17).

Key findings:

- LlamaIndex `AutoMergingRetriever` + `HierarchicalNodeParser` is the most mature parent-child implementation: default hierarchy 2048→512→128 tokens, merge threshold 50%.
- BGE-M3 maintainer: "a chunk size of 512 is enough." Wiki guide: 512-token chunks, 128-token overlap (25%).
- Structure-aware splitting (using Docling's heading hierarchy) is deterministic, free, and produces high-quality boundaries. Semantic chunking (embedding-based) gives 20–70% improvement but costs more at ingestion.
- Docling's `DoclingDocument` tree structure maps directly to hierarchical chunks: section headers = parent chunks, paragraphs = leaf chunks.

## Decision

### 1. Structure-aware chunking as the primary strategy

Walk Docling's `DoclingDocument` body tree to create chunks at structural boundaries (headings, sections, paragraphs, tables, formulas). Do **not** use fixed-size or recursive-character splitting as the primary strategy.

**Fallback:** When a structural unit (e.g., a very long paragraph) exceeds the maximum leaf chunk size, apply recursive-character splitting within that unit to stay within bounds.

### 2. Two-level parent-child hierarchy

| Level | Role | Target size | Stored in |
|-------|------|-------------|-----------|
| **Parent** | Context expansion at generation time | 1024–2048 tokens | Postgres `chunks` table (parent row) + Qdrant payload (not independently embedded) |
| **Leaf** | Retrieval unit (embedded and indexed) | 128–512 tokens | Postgres `chunks` table (leaf row) + Qdrant vectors + OpenSearch documents |

- Only leaf chunks are embedded with BGE-M3 and indexed in Qdrant/OpenSearch.
- Parent chunks are stored in Postgres and retrieved by ID when the retrieval pipeline's parent-child expansion stage fires.
- The merge threshold (what fraction of sibling leaves must be retrieved before the parent replaces them) is a **runtime retrieval parameter**, not a chunking parameter. Default: 0.5 (50%), matching LlamaIndex's proven default.

### 3. Profile-specific routing

**Book profile:**
- Parent chunks = sections/subsections (defined by heading hierarchy in Docling output).
- Leaf chunks = paragraphs, definitions, formulas, tables, figures within each section.
- Heading path preserved on every chunk: `["Chapter 3", "Section 3.2", "Definition 3.2.1"]`.
- Tables and formulas are **atomic** — never split across chunks. If a table exceeds the leaf max, it becomes its own parent chunk.
- Page ranges preserved from Docling's `page_no` metadata.

**Loose document profile:**
- Parent chunks = top-level sections (if any structural headings exist) or the full document (if flat).
- Leaf chunks = paragraphs or type-specific units (clauses for contracts, messages for emails, key-value pairs for forms).
- Metadata enrichment: every leaf chunk carries document-level metadata (type, date, author, version, tenant, ACL) in addition to structural position.
- Type routing: the chunker inspects `document_type` to apply type-specific rules (clause boundaries for contracts, sender boundaries for emails, section headings for reports).

### 4. Concrete defaults

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| Leaf max tokens | 512 | BGE-M3 optimal; maintainer recommendation |
| Leaf min tokens | 64 | Below this, merge with sibling or parent |
| Parent max tokens | 2048 | Enough context for synthesis; LlamaIndex default |
| Overlap (leaf) | 0 tokens (structure-defined) | Structure-aware boundaries make character overlap unnecessary; heading path prepended instead |
| Heading prepend | Yes — parent heading text included in leaf chunk text before embedding | Gives the embedding model full context path without artificial overlap |
| BGE-M3 `max_length` | 512 | Model default |
| Merge threshold (retrieval) | 0.5 | LlamaIndex default; 50% of siblings triggers parent merge |

### 5. Chunker interface

```python
class Chunker(Protocol):
    def chunk(self, parsed_document: ParsedDocument, profile: DocumentProfile) -> list[Chunk]:
        """Produce a list of chunks with parent-child relationships.

        Idempotent: same input always produces same output.
        """
        ...
```

- `ParsedDocument` wraps the Docling JSON output.
- `DocumentProfile` is an enum: `BOOK`, `LOOSE`.
- Returns a flat list of `Chunk` objects; parent-child relationships expressed via `parent_id` field.
- The chunker is **deterministic**: same parsed document + same profile = same chunks in same order. This enables idempotent re-chunking.

### 6. Ingestion pipeline integration

New stage in `PipelineRunner`:

```
parse → chunk → embed → index_qdrant → index_opensearch → quality_report
```

The `chunk` stage:
1. Reads the parsed artifact from the previous stage.
2. Routes to `BookChunker` or `LooseChunker` based on `source_type`.
3. Produces chunks, persists them to the `chunks` table.
4. Records chunk count and size statistics in the stage's `output_artifacts`.
5. Passes the chunk list to the next stage (embed).

## Consequences

### Positive

- **Precise retrieval**: 512-token leaf chunks produce focused BGE-M3 embeddings, avoiding the "blurry embedding" problem of large chunks.
- **Rich generation context**: parent-child expansion gives the LLM 1024–2048 tokens of coherent context when multiple sibling chunks are retrieved.
- **Deterministic and idempotent**: structure-aware chunking from Docling's tree is fully deterministic — same input always produces same chunks. No threshold-dependent or non-deterministic boundary detection.
- **Zero ingestion overhead**: structure-aware splitting uses Docling's already-parsed hierarchy. No extra embedding or LLM calls during chunking.
- **Citation-ready**: every chunk carries heading path, page range, and source coordinates — exactly what the citation resolver needs.
- **Profile flexibility**: book and loose-document profiles share the same `Chunker` interface and `chunks` table but apply different boundary rules.

### Negative

- **~2x storage**: both parent and leaf chunks are stored in Postgres. Parent chunks are not embedded (no vector cost), but they occupy rows. For a corpus of 10K documents averaging 200 chunks each, this is ~4M rows — well within Postgres capacity.
- **Docling structure dependency**: chunk quality depends on Docling's heading detection accuracy. Poorly structured PDFs (no heading styles) may produce flat trees, degrading to near-fixed-size behavior. Mitigated by the recursive-character fallback for oversized units.
- **Table/formula atomicity constraint**: very large tables (>2048 tokens) cannot fit in a single parent chunk. These must be split by rows with header repetition, which is a later refinement (not in the initial implementation).
- **No semantic boundary detection initially**: structure-aware chunking is good but not optimal. Semantic chunking (embedding-based boundary detection) could improve quality by 20–70% per research, but at significant ingestion cost. This is a Phase 7 candidate (ADR-0003 class: measured weakness required before adoption).
- **Overlap is zero for structure-defined chunks**: heading prepending compensates, but cross-boundary queries (where the answer spans two adjacent sections) may retrieve only one section. The merge threshold at retrieval time partially mitigates this.

## Alternatives considered

### A. Fixed-size chunking (512 tokens, 128-token overlap)

Simple, predictable, no structure dependency. But: chunks split mid-sentence, mid-paragraph, mid-table. Embeddings capture incomplete semantic units. Heading context lost. Rejected because Docling provides structural signals for free — ignoring them wastes the parser's work.

### B. Three-level hierarchy (2048→512→128 tokens)

LlamaIndex's default. Adds a grandparent level for very large context. Rejected for initial implementation because: (1) adds complexity (3 levels of merge logic), (2) no evidence that 3 levels outperform 2 levels on the target corpus, (3) can be added later if eval shows the 2-level parent (2048 tokens) is insufficient for synthesis. Two levels are simpler and sufficient to start.

### C. Semantic chunking (embedding-based boundary detection)

Embeds every sentence during ingestion, splits where cosine similarity drops. Produces the most semantically coherent chunks. Rejected as default because: (1) significant ingestion cost (one embedding per sentence), (2) threshold-dependent (non-deterministic across runs if the model changes), (3) structure-aware chunking from Docling is free and produces high-quality boundaries. Deferred to Phase 7 as an opt-in upgrade path.

### D. LLM-based chunking (Meta-Chunking)

Uses LLM perplexity to detect logical boundaries. Highest quality but requires LLM calls during ingestion — expensive and non-deterministic. Rejected for the same reasons as semantic chunking, plus air-gapped deployment readiness requires minimizing LLM dependency at ingestion time.

### E. No parent-child (flat chunks only)

Simpler: every chunk is independent, no hierarchy. Rejected because: (1) the retrieval pipeline in ARCHITECTURE.md already specifies parent-child expansion, (2) flat chunks force a choice between too-small (poor generation context) and too-large (poor retrieval precision), (3) the parent-child pattern is well-proven in LlamaIndex and production RAG systems.

## References

- Research note: `docs/uber-rag/research/2026-05-17-chunking-strategies.md` (2026-05-17)
- LlamaIndex AutoMergingRetriever: https://docs.llamaindex.ai/en/stable/examples/retrievers/auto_merging_retriever/ (accessed 2026-05-17)
- LlamaIndex HierarchicalNodeParser: https://developers.llamaindex.ai/python/framework/module_guides/loading/node_parsers/modules/ (accessed 2026-05-17)
- BGE-M3 model card: https://huggingface.co/BAAI/bge-m3 (accessed 2026-05-17)
- BGE-M3 maintainer chunk size recommendation: https://huggingface.co/BAAI/bge-m3/discussions/59 (accessed 2026-05-17)
- BGE-M3 paper: https://arxiv.org/abs/2402.03216 (accessed 2026-05-17)
- Docling document concept: https://github.com/docling-project/docling/blob/4e650af5/docs/concepts/docling_document.md (accessed 2026-05-17)
- Docling export formats: https://mintlify.com/docling-project/docling/guides/export-formats (accessed 2026-05-17)
- Recursive Semantic Chunking (ICNLSP 2025): https://aclanthology.org/2025.icnlsp-1.15.pdf (accessed 2026-05-17)
- Meta-Chunking: https://arxiv.org/pdf/2410.12788 (accessed 2026-05-17)
- Domain model: `docs/uber-rag/DOMAIN_MODEL.md` — `chunks` table
- Ingestion pipelines: `docs/uber-rag/INGESTION_PIPELINES.md` — chunking step and provenance
- ADR-0002: Ingestion orchestration (idempotency rules)
- ADR-0004: LLM adapter (BGE-M3 embedding model)
- ADR-0011: Structured document understanding (Docling parser, deployment profiles)

## Revisit triggers

- **If cross-boundary retrieval recall < 70% on the held-out eval set**, consider adding 64–128 token overlap to leaf chunks or adopting semantic boundary detection.
- **If parent context (2048 tokens) is insufficient for synthesis questions**, consider adding a third hierarchy level (grandparent at 4096 tokens).
- **If Docling heading detection accuracy < 80% on the target corpus** (measured by comparing detected headings against manual annotation), add a fallback to recursive-character splitting with heading prepending.
- **If BGE-M3 is superseded by a model with different optimal chunk size**, re-evaluate leaf max tokens.
- **If table-heavy corpora produce many oversized-table warnings**, implement row-level table splitting with header repetition.
