# Ingestion Pipelines

## Shared ingestion steps

```text
upload
  -> hash
  -> deduplicate
  -> detect file type
  -> store original
  -> create ingestion job
  -> parse
  -> OCR if required
  -> normalize
  -> extract structure
  -> chunk
  -> embed
  -> index lexical
  -> index vector
  -> quality report
  -> publish searchable version
```

## Book profile

Book ingestion must preserve hierarchy and pages.

Required units:

- book metadata
- table of contents
- chapter
- section
- subsection
- page
- paragraph
- definition
- theorem if relevant
- formula
- table
- figure
- example
- glossary term
- index term

Chunking:

- child chunks: precise retrieval, often 200 to 600 tokens
- parent sections: context expansion, often 1500 to 4000 tokens
- summaries: navigation only, not final evidence

Provenance:

- document id
- page range
- heading path
- source coordinates where available
- parser version
- chunker version
- source hash

## Loose document profile

Loose documents need metadata and type routing.

Required metadata:

- document type
- title
- source
- author/owner
- date
- version
- tenant
- ACL
- tags
- attachments
- language

Type-specific handling:

- contract: clauses, parties, dates, obligations, exact identifiers
- report: sections, tables, figures, executive summary
- email: sender, recipients, thread, attachments, dates
- manual/spec: sections, procedures, warnings, tables
- spreadsheet: sheets, tables, columns, rows, cells

## Quality report

Each ingestion job must produce a quality report. See `templates/quality_report.schema.json`.

Minimum fields:

- pages expected
- pages parsed
- OCR pages
- OCR confidence if available
- tables detected
- formulas detected
- figures detected
- TOC detected
- chunks created
- warnings
- failed pages
- parser version
- embedding model version
- index status
