# Retrieval and Answer Quality

## Quality principle

Reliable answers require reliable retrieval. The LLM is not a substitute for retrieval correctness.

## Query router routes

- exact route: IDs, quote search, page references, filenames, rare terms
- semantic route: concept explanations and paraphrases
- book route: textbook, chapter, section, definition, formula, example questions
- table route: row/column/cell questions
- formula route: equation and symbol questions
- cross-corpus route: compare textbook knowledge with loose documents
- negative route: determine if evidence is absent

## Candidate generation

Use multiple candidate sources:

- OpenSearch/Tantivy BM25
- phrase/exact search
- Qdrant dense vector search
- Qdrant sparse vector search
- definition index
- table index
- formula index
- section/chapter summary index for navigation only

## Fusion

Use RRF or DBSF. Deduplicate by source span and parent section. Apply diversity limits to avoid one document dominating unless the query is scoped to that document.

## Reranking

Use BGE-reranker-v2-m3 or equivalent cross-encoder on top candidates. Keep top-k reasonable and measure latency.

## Context builder

For each selected chunk:

- include source metadata
- include heading path
- include page range
- include parent section when needed
- include neighboring definitions or formulas only when useful
- preserve table structure for table queries

## Answer rules

- Every factual claim must be traceable to a citation.
- Direct evidence, summary, and inference must be distinguishable.
- If sources are insufficient, return not-found or partial.
- Do not cite summaries as final evidence unless the source itself is a human-authored summary.
- Use generated summaries only as navigation.

## Sentence-level verifier

For each answer sentence:

```json
{
  "sentence": "string",
  "supported": true,
  "citation_ids": ["string"],
  "support_type": "direct|inferred|unsupported",
  "action": "keep|weaken|remove"
}
```

## Required eval cases

- exact phrase
- rare term
- page lookup
- definition lookup
- formula lookup
- table lookup
- semantic paraphrase
- chapter-level question
- cross-book comparison
- book vs loose document comparison
- negative question
- ACL leakage question
- deleted document question
- OCR noise question
