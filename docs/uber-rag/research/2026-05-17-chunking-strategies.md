# Research Note: RAG Chunking Strategies
Date: 2026-05-17
Status: Draft

## Bottom Line

Chunking is the single most impactful decision in a RAG pipeline — it determines what the retriever can find before any model is involved. For Uber-RAG, the research points to a **parent-child / small-to-big retrieval** pattern as the best fit: embed small chunks (128–512 tokens) for precise retrieval, but expand to parent chunks (1024–2048 tokens) at generation time. BGE-M3's default `max_length=512` and 8192-token ceiling align well with this pattern. Docling's `DoclingDocument` format provides exactly the structural signals (heading hierarchy, page numbers, tables, formulas, groups) needed to drive boundary-aware chunking rather than naive fixed-size splitting. For loose documents (contracts, emails, reports), the strategy shifts from hierarchy-based splitting to metadata-enriched semantic chunking with type-specific routing.

---

## 1. Parent-Child / Small-to-Big Retrieval

### LlamaIndex: AutoMergingRetriever + HierarchicalNodeParser

**Implementation pattern:**
- `HierarchicalNodeParser` splits a document into a recursive hierarchy of nodes at multiple chunk sizes
- Default hierarchy: **2048 → 512 → 128 tokens** (3 levels)
- Only **leaf nodes** (smallest chunks) are indexed in the vector store
- All nodes (including parents) are stored in a `docstore` keyed by node ID
- Each child node carries a `parent_node` reference (node ID)

**Retrieval-time behavior (AutoMergingRetriever):**
1. Retrieve leaf nodes via similarity search (top-k, typically 6–12)
2. Group retrieved leaves by parent node
3. If the ratio of retrieved children to total children exceeds a threshold (default `simple_ratio_thresh=0.5`), **merge** — replace those children with the parent node
4. Recurse upward: if merged parents also cluster under a grandparent, merge again
5. Result: fewer, larger, more coherent chunks passed to the LLM

**Concrete numbers:**
- Default chunk sizes: `[2048, 512, 128]`
- Merge threshold: 50% of siblings must be retrieved before parent replaces them
- Typical top-k for leaf retrieval: 6–12
- Parent score = average of children's scores

**LlamaIndex Recursive Retriever (alternative pattern):**
- Uses `IndexNode` references: small chunks point to a bigger parent chunk via `IndexNode.from_text_node(sn, base_node.node_id)`
- Sub-chunk sizes used in examples: `[128, 256, 512]`
- At retrieval time, the recursive retriever follows the reference to return the parent chunk
- Evaluated: chunk references and metadata references both outperform raw chunk retrieval on hit-rate and MRR

### LangChain: No built-in parent-child

LangChain does not have a native parent-child retrieval pattern. The pattern must be implemented manually:
- Split into large chunks (parents), then sub-split into small chunks (children)
- Store parent-child mapping in metadata
- Retrieve on children, expand to parent at generation time

### Production guidance (Viqus, 2026):
- **Embed small chunks (256 tokens) for retrieval, map to parent chunks (1024 tokens) for generation**
- "This gives you the best of both worlds: precise retrieval (because small chunks produce focused embeddings) and rich context (because the model sees the surrounding information)"
- Storage cost: approximately 2x (both parent and child chunks stored)

### Sources
- LlamaIndex AutoMergingRetriever docs: https://docs.llamaindex.ai/en/stable/examples/retrievers/auto_merging_retriever/ · Accessed: 2026-05-17 · Reliability: official
- LlamaIndex HierarchicalNodeParser API: https://developers.llamaindex.ai/python/framework/module_guides/loading/node_parsers/modules/ · Accessed: 2026-05-17 · Reliability: official
- LlamaIndex source: https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/retrievers/auto_merging_retriever.py · Accessed: 2026-05-17 · Reliability: repo
- LlamaIndex Recursive Retriever: https://developers.llamaindex.ai/python/examples/retrievers/recursive_retriever_nodes/ · Accessed: 2026-05-17 · Reliability: official
- Viqus chunking strategies 2026: https://viqus.ai/blog/rag-chunking-strategies-2026 · Accessed: 2026-05-17 · Reliability: secondary

---

## 2. Chunk Size and Overlap

### BGE-M3 Specifics

**Model specs:**
- Max sequence length: **8192 tokens**
- Default `max_length` for encoding: **512 tokens**
- Dimension: 1024
- Supports dense, sparse (lexical), and ColBERT (multi-vector) retrieval simultaneously

**Chunk size recommendations for BGE-M3:**
- BGE-M3 maintainer (on HuggingFace discussions): **"a chunk size of 512 is enough"**
- Wiki guide recommends: **512-token chunks with 128-token overlaps** (25% overlap)
- For complex reasoning chunks: increase to 2048 or 4096
- Query encoding: keep at 512 tokens
- Hybrid search weight ratio: **0.7 dense / 0.3 sparse**

**Key insight:** BGE-M3's 8192-token ceiling means you *can* embed very long chunks, but performance degrades. The model was trained with a default of 512 tokens. Going beyond 512–1024 tokens per chunk for dense retrieval is not recommended unless you specifically need long-context matching.

### General chunk size guidance (cross-source consensus)

| Use Case | Chunk Size | Overlap | Source |
|---|---|---|---|
| Q&A / factual lookup | 256–512 tokens | 10–15% (50–75 tok) | Multiple |
| General RAG (default) | 512 tokens | 10–20% (50–100 tok) | Multiple |
| Summarization | 1024–2048 tokens | 5% | Callsphere |
| Legal/medical | 512–1024 tokens | 15–20% | Callsphere |
| Code search | 64–256 tokens | 0% | Callsphere |
| Dense retrieval (BGE-M3) | 512 tokens | 128 tokens (25%) | BGE-M3 wiki |
| Parent chunk (hierarchical) | 1024–2048 tokens | N/A (children overlap) | LlamaIndex |

### Overlap specifics

- **10–20% of chunk size** is the standard recommendation across all sources
- A Reddit study cited by Amir Teymoori: adding 64-token overlap improved dense retrieval precision by **14.5%** (0.173 → 0.198)
- Overlap > 20% causes "explosive token bloat" in retrieval — stay under 15% in production (Neural Base)
- For BGE-M3 specifically: 128-token overlap on 512-token chunks (25%) is recommended by the wiki guide, which is higher than the general 10–20% rule — this may reflect BGE-M3's training

### Dense vs. lexical retrieval differences

- **Dense retrieval**: benefits from smaller chunks (256–512 tokens) because the embedding represents a focused concept. Larger chunks produce "blurry" embeddings that average multiple topics.
- **Lexical/BM25 retrieval**: can tolerate larger chunks because it matches on exact terms regardless of chunk size. However, very large chunks dilute BM25 scores.
- **Hybrid (BGE-M3 dense + sparse)**: 512 tokens is the sweet spot — dense gets focused embeddings, sparse gets enough context for term matching.

### Sources
- BGE-M3 model card: https://huggingface.co/BAAI/bge-m3 · Accessed: 2026-05-17 · Reliability: official
- BGE-M3 HuggingFace discussion #59: https://huggingface.co/BAAI/bge-m3/discussions/59 · Accessed: 2026-05-17 · Reliability: official (maintainer response)
- BGE-M3 wiki guide: https://wiki.charleschen.ai/ai/processed/wiki/llm-core/rag/queries/embedding/how-to-use-baaibge-m3-embedding-model · Accessed: 2026-05-17 · Reliability: secondary
- BGE-M3 paper: https://arxiv.org/abs/2402.03216 · Accessed: 2026-05-17 · Reliability: paper
- Amir Teymoori chunking strategies: https://amirteymoori.com/rag-text-chunking-strategies/ · Accessed: 2026-05-17 · Reliability: secondary
- Callsphere chunking guide: https://callsphere.ai/blog/document-chunking-strategies-rag-fixed-semantic-recursive.md · Accessed: 2026-05-17 · Reliability: secondary
- Neural Base LangChain guide: https://theneuralbase.com/langchain/learn/intermediate/recursivecharactertextsplitter-the-standard-splitter/ · Accessed: 2026-05-17 · Reliability: secondary

---

## 3. Boundary-Aware Chunking

### What it is

Boundary-aware chunking respects document structure (headings, paragraphs, tables, formulas, lists) rather than splitting at arbitrary character/token boundaries. The goal: each chunk is a semantically complete unit.

### Approaches

**1. Recursive character splitting (LangChain default)**
- Tries separators in order: `\n\n` → `\n` → `. ` → ` ` → ``
- Falls back to character-level splitting only as last resort
- Works for 80% of cases but doesn't understand document structure
- Default config: `chunk_size=1000, chunk_overlap=200` (characters, not tokens)

**2. Markdown/HTML-aware splitting**
- LangChain's `MarkdownHeaderTextSplitter` splits on markdown headers (`#`, `##`, `###`)
- Preserves heading hierarchy as metadata on each chunk
- Headers prepended to chunk text before embedding → vector captures full context path
- Best for: technical docs, wikis, README files

**3. Semantic chunking**
- Embed each sentence, compute cosine similarity between adjacent sentences
- Split where similarity drops below threshold (topic boundary)
- Produces the most semantically coherent chunks
- Cost: requires embedding every sentence during ingestion
- Claimed improvement: up to 60–70% accuracy improvement over naive fixed-size chunking (RagAboutIt, 2026)

**4. Recursive Semantic Chunking (RSC) — ICNLSP 2025 paper**
- Recursively splits chunks exceeding threshold (1,500 characters)
- Merges small chunks with most similar neighbor
- Gradually reduces breakpoint threshold per recursion level
- Outperformed recursive character split, semantic chunking, and agentic chunking on contextual relevancy metrics

**5. Meta-Chunking (arXiv 2410.12788)**
- Uses LLM perplexity and margin sampling to detect logical boundaries
- Dynamic merging balances fine-grained and coarse-grained segmentation
- Two-stage hierarchical summary generation for global information compensation
- Three-stage text chunk rewriting (missing reflection → refinement → completion)
- Higher quality but requires LLM calls during ingestion

### Tradeoffs

| Strategy | Semantic Quality | Ingestion Cost | Speed | Determinism |
|---|---|---|---|---|
| Fixed-size | Low | Free | Fast | Yes |
| Recursive character | Medium | Free | Fast | Yes |
| Structure-aware (headings) | High | Free | Fast | Yes |
| Semantic (embedding-based) | High | Embedding cost per sentence | Slow | Threshold-dependent |
| LLM-based (Meta-Chunking) | Highest | LLM cost per chunk | Slowest | Non-deterministic |

### Production recommendation

Start with **structure-aware splitting** (using Docling's parsed hierarchy) as the primary strategy. Fall back to recursive character splitting for sections that exceed max chunk size. Reserve semantic chunking for high-value documents where ingestion cost is justified.

### Sources
- Recursive Semantic Chunking paper: https://aclanthology.org/2025.icnlsp-1.15.pdf · Accessed: 2026-05-17 · Reliability: paper
- Meta-Chunking paper: https://arxiv.org/pdf/2410.12788 · Accessed: 2026-05-17 · Reliability: paper
- RagAboutIt semantic boundaries: https://ragaboutit.com/the-chunking-strategy-shift-why-semantic-boundaries-cut-your-rag-errors-by-60/ · Accessed: 2026-05-17 · Reliability: secondary
- Callsphere chunking guide: https://callsphere.ai/blog/document-chunking-strategies-rag-fixed-semantic-recursive.md · Accessed: 2026-05-17 · Reliability: secondary
- Aaron's deep dive: https://niceboy.org/en/posts/2025/02/rag-chunking-strategies/ · Accessed: 2026-05-17 · Reliability: secondary

---

## 4. Loose Document Chunking

### The problem

Loose documents (contracts, reports, emails, memos, invoices) have **shallow hierarchy** but **rich metadata**. Unlike books with deep heading structures (Part > Chapter > Section > Subsection), a contract might have: Title → Sections → Clauses. An email has: Subject → Body (flat).

### Strategies by document type

**Contracts:**
- Parent-child pattern with contextual enrichment: **300-token children / 1500-token parents** (Enrico Piovano)
- Split on clause/section boundaries (numbered sections, "WHEREAS", "ARTICLE X")
- Metadata: parties, effective date, jurisdiction, contract type, clause numbers
- Higher overlap (15–20%) because cross-clause references are common

**Reports (financial, compliance):**
- Document-aware chunking: split on section headings
- Chunk size: 512 tokens
- Metadata: report type, fiscal period, section hierarchy, page numbers
- Tables kept as complete units (never split a table across chunks)

**Emails:**
- Split on conversational boundaries (sender changes, thread breaks)
- Isolate latest message from quoted history
- Remove signatures and disclaimers before chunking
- Metadata: sender, timestamp, subject, thread ID, recipients
- Treat each message as a chunk; merge thread context at retrieval time

**Invoices / forms:**
- Key-value extraction rather than chunking — each field is a retrieval unit
- Metadata: vendor, date, amount, PO number, line items

### Metadata enrichment for loose documents

Every chunk should carry:
1. **Structural position**: section title, heading hierarchy, page number
2. **Document metadata**: title, author, date, document type
3. **Chunk relationships**: previous/next chunk IDs, parent document ID
4. **Generated metadata** (optional, higher cost):
   - 1–2 sentence summary of chunk content
   - Questions the chunk could answer
   - Key entities (people, organizations, amounts, dates)
   - Keywords for hybrid retrieval

### Type routing

Production systems route documents to different chunking strategies based on document type:
- **Structured docs** (reports, papers, manuals) → Docling → structure-aware splitting
- **Contracts/legal** → clause-aware splitting + parent-child
- **Emails** → conversation-aware splitting
- **Short/uniform** (tickets, FAQs) → fixed-size or per-entry splitting

### Sources
- Enrico Piovano document processing pipelines: https://enricopiovano.com/blog/document-processing-pipelines-llm-applications/ · Accessed: 2026-05-17 · Reliability: secondary
- Particula Tech context preservation: https://particula.tech/blog/document-chunking-rag-context-preservation · Accessed: 2026-05-17 · Reliability: secondary
- Shalinibs document parsing for RAG: https://medium.com/@shalinibs7076/document-parsing-for-rag-why-structure-matters-before-embeddings-f23d73f65eee · Accessed: 2026-05-17 · Reliability: secondary
- Cohere chunking strategies: https://docs.cohere.ai/page/chunking-strategies · Accessed: 2026-05-17 · Reliability: official

---

## 5. Docling Output Structure

### DoclingDocument format (v2)

Docling produces a `DoclingDocument` — a Pydantic data model with these top-level fields:

**Content items:**
- `texts`: list of `TextItem` subtypes — `TitleItem`, `SectionHeaderItem`, `ListItem`, `CodeItem`, `FormulaItem`, `FieldHeadingItem`, `FieldValueItem`, `TextItem` (paragraphs)
- `tables`: list of `TableItem` — carries structure annotations (rows, cols, headers, body)
- `pictures`: list of `PictureItem` — carries structure annotations
- `key_value_items`: list of key-value pairs

**Content structure (tree):**
- `body`: root node of a tree structure for the main document body
- `furniture`: root node for headers, footers, page numbers (non-body content)
- `groups`: container items that don't represent content directly — e.g., lists, chapters

**Hierarchy mechanism:**
- Items reference parents and children through **JSON pointers** (e.g., `#/texts/5`)
- The `body` tree encodes reading order via children ordering
- Headings create natural hierarchy: all items under a heading are nested as its children
- Groups can contain both text items and other groups (recursive nesting)

**Metadata available per item:**
- Page number (`page_no`)
- Bounding boxes (layout coordinates, if available from PDF)
- Provenance information (source location in original document)
- Item type (paragraph, section header, title, list item, code, formula, table, etc.)

**Export formats:**
| Format | Structure | Images | Best For |
|---|---|---|---|
| JSON | Full (lossless) | Embedded/Linked | Programmatic access, chunking pipelines |
| DocTags | Semantic tags | No | NLP pipelines, text analysis |
| Markdown | Basic | Embedded/Linked | Human reading, simple RAG |
| HTML | Rich | Embedded/Linked | Web display |
| Plain text | None | No | Search indexing |

### DocTags example (shows structural elements):

```xml
<title>Document Title</title>
<section-header>Section 1</section-header>
<paragraph>This is a paragraph with bold and italic text.</paragraph>
<subsection-header>Subsection 1.1</subsection-header>
<list-item>Bullet point 1</list-item>
<list-item>Bullet point 2</list-item>
<table>
  <row><cell>Header 1</cell><cell>Header 2</cell></row>
  <row><cell>Cell 1</cell><cell>Cell 2</cell></row>
</table>
```

### What this means for Uber-RAG chunking

Docling's output provides **exactly the signals needed for boundary-aware chunking**:

1. **Heading hierarchy** → natural chunk boundaries at section/subsection level
2. **Item types** → different chunking rules for paragraphs vs. tables vs. formulas vs. code
3. **Page numbers** → metadata for citation and filtering
4. **Tree structure** → parent-child relationships already encoded; can map directly to LlamaIndex-style hierarchical nodes
5. **Groups** → list items stay together; chapters are natural parent chunks
6. **Furniture separation** → headers/footers excluded from chunks automatically

**Implementation path:** Parse Docling JSON → walk the `body` tree → create chunks at configurable depth levels (e.g., section headers = parent chunks, paragraphs = leaf chunks) → preserve heading path as metadata on each chunk.

### Sources
- Docling export formats: https://mintlify.com/docling-project/docling/guides/export-formats · Accessed: 2026-05-17 · Reliability: official
- Docling document concept: https://github.com/docling-project/docling/blob/4e650af5/docs/concepts/docling_document.md · Accessed: 2026-05-17 · Reliability: repo
- Docling API reference: https://docling-project.github.io/docling/reference/docling_document/ · Accessed: 2026-05-17 · Reliability: official
- Docling technical report: https://arxiv.org/html/2408.09869v4 · Accessed: 2026-05-17 · Reliability: paper

---

## Implementation Impact for Uber-RAG

### Recommended chunking architecture

```
Docling parse
  → DoclingDocument JSON
  → Structure-aware chunker (walks body tree)
    → Book pipeline: heading hierarchy → parent-child nodes
    → Loose pipeline: type routing → metadata-enriched chunks
  → BGE-M3 encode (max_length=512, dense + sparse)
  → Qdrant store (leaf nodes) + docstore (parent nodes)
  → AutoMergingRetriever at query time
```

### Concrete defaults to start with

| Parameter | Value | Rationale |
|---|---|---|
| Leaf chunk size | 128–512 tokens | BGE-M3 optimal at 512; smaller for dense factual content |
| Parent chunk size | 1024–2048 tokens | LlamaIndex default; enough context for synthesis |
| Overlap (leaf) | 64–128 tokens | 10–25% of chunk size; 128 for BGE-M3 per wiki guide |
| Merge threshold | 0.5 | LlamaIndex default; 50% of siblings triggers parent merge |
| BGE-M3 max_length | 512 | Model default; maintainer recommendation |
| Hybrid weights | 0.7 dense / 0.3 sparse | BGE-M3 wiki recommendation |

### Open questions

1. **Docling → chunker adapter**: Need to design the mapping from DoclingDocument tree to hierarchical chunks. Should section headers be parent chunks? Should the tree depth be configurable per document profile?
2. **Table chunking**: Docling preserves table structure, but tables can be very large. Need a strategy: keep small tables as single chunks, split large tables by rows with header repetition?
3. **Formula handling**: Docling identifies `FormulaItem` — should formulas be chunked separately or kept with surrounding paragraph context?
4. **Overlap strategy for structure-aware chunking**: When chunks are defined by structure (not fixed-size), overlap is less natural. Should we use heading prepending (include parent heading text in each child chunk) instead of character overlap?
5. **Loose document type routing**: Need a classifier or heuristic to route documents to the correct chunking strategy. How much of this can be derived from Docling's detected structure vs. requiring explicit metadata?
6. **Evaluation**: Need a held-out evaluation set that specifically tests chunking quality — cross-chunk answers, table queries, formula lookups, and boundary-spanning questions.

---

## Escalation Note

This research covered 5 distinct areas across 15+ sources. The following sub-questions remain that would benefit from DeepEye investigation:

1. **BGE-M3 chunk size ablation**: The maintainer says "512 is enough" but there's no published ablation study. A DeepEye search could find benchmark results comparing 256 vs 512 vs 1024 token chunks with BGE-M3 specifically.

2. **Docling → chunker production implementations**: No production reference architecture found that chains Docling output directly into a hierarchical chunker. This is a gap that requires either building from scratch or deeper research into existing integrations.

3. **Chunking evaluation methodology**: How to measure chunking quality independently from retrieval quality. The Recursive Semantic Chunking paper and Meta-Chunking paper propose metrics but there's no consensus framework.
