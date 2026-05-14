# Research Protocol

## Goal

Keep the project technically current and source-backed. Every major dependency choice, API behavior, security assumption, or model capability must be tied to an official source, paper, or reproducible benchmark.

## Source authority (strict)

Sources are tiered. ADRs and `STACK_REFERENCES.md` cite **Tier 1 and Tier 2 only**. Tier 3 may inform discovery but never serves as primary evidence.

### Tier 1 — citable as primary evidence in ADRs

- Official project documentation (e.g., docs.fastapi.tiangolo.com, qdrant.tech/documentation, opensearch.org/docs)
- Official project repositories (README, source code, official examples directory)
- Primary research papers (arXiv, conference proceedings, journal publications)
- Vendor model cards on the publishing organization's primary platform (Hugging Face org page for BAAI, Mistral, Qwen, Meta; GitHub Releases for runtime libraries)
- Standards and specifications (RFC, W3C, OpenAPI spec, OIDC spec, JOSE/JWT specs)
- Official release notes and changelogs

### Tier 2 — citable with caveat, supports Tier 1 evidence

- Maintainer-authored issues and discussions in the official repo
- Maintainer-authored blog posts on the official project site or organization site
- Recorded conference talks by maintainers
- Reproducible benchmarks with published code AND dataset (both required)

### Tier 3 — discovery only, never sole evidence

- Third-party blog posts and tutorials
- Aggregator sites (Medium, Dev.to, Substack, Hacker News comments)
- AI-generated summaries (LLM outputs, including DeepEye synthesis — DeepEye findings must always trace back to Tier 1 or Tier 2 sources)
- Slide decks without authoritative provenance
- Forum posts (StackOverflow, Reddit) — useful for "is this a known problem?", not for "what is the answer?"

### Disallowed

- SEO-farm content and content-mill articles
- Pirated PDFs or scraped reposts of paywalled content
- Marketing pages making claims without linked supporting documentation
- Anything dated more than 12 months ago for fast-moving libraries (vLLM, Qdrant, OpenSearch, model serving runtimes), unless explicitly re-verified as still current

## Phase-entry research checklist

Run this at the start of every phase (see `ROADMAP.md`):

1. **Scan [IAAR-Shanghai/Awesome-AI-Memory](https://github.com/IAAR-Shanghai/Awesome-AI-Memory)** for:
   - New papers in the past 60 days relevant to the phase's deliverables.
   - New tools or projects listed since the last phase entry.
   - Changes to recommendations in curated sections (e.g., new "must-read" entries).

2. **For every pinned dependency in the phase scope:**
   - Read the latest release notes.
   - Check the official issue tracker for security advisories and breaking-change notices.
   - Verify the version pin in `STACK_REFERENCES.md` is still current and supported.

3. **For every model referenced in the phase scope:**
   - Re-read the model card on Hugging Face (or equivalent primary source).
   - Check for a newer version or successor.
   - If a successor exists, note it as a candidate. Do not silently swap.

4. **For every architectural pattern referenced in the phase scope:**
   - Search Awesome-AI-Memory for newer techniques.
   - If a technique has been superseded by curated consensus, propose an ADR update.

5. **Produce a one-page phase-entry research note** at `docs/uber-rag/research/YYYY-MM-DD-phase-N-entry.md` containing:
   - What was checked (bullet list of sources scanned).
   - What changed since the last phase entry.
   - What requires a new or reopened ADR.
   - What was confirmed unchanged (still valid pins).

6. **Block phase start** if step 4 or 5 surfaces an unresolved material change. Close the new ADR before starting, or accept the risk in writing with an explicit revisit trigger.

## When to research (mid-phase)

Research is mandatory whenever:

- A dependency version, API behavior, or library default may have changed.
- A model card has been updated since the last research note.
- A security or ACL pattern is being implemented for the first time.
- A benchmark or eval metric is being defined.
- A performance or scaling claim is being made.
- A licensing question arises.
- A new architectural pattern is being considered.

## DeepEye usage

`search/deepeye` is the project's deep-research weapon (deepseek-v4-pro backbone, 8 subagents: worker, proxy, scrapling, crawlee, translator-normalizer, instagram, maps, vision). Dispatch DeepEye for:

- Multi-source comparison with measurable tradeoffs (reranker bake-off, embedding model bake-off, lexical engine bake-off).
- ADR-bound decisions where authority-source scraping is needed.
- Multilingual or cross-domain research where breadth matters.
- Any phase-entry check that surfaces a non-trivial change.

DeepEye outputs are **synthesized findings** — always trace each finding back to a Tier 1 or Tier 2 source before citing in an ADR. DeepEye's own write-up is Tier 3 unless and until you have verified the underlying sources.

If DeepEye is unavailable, fall back to direct Exa search + webfetch and note the gap in the research note.

## Substrate exclusions

The project does **not** use n8n as a research or production substrate (see ADR-0005). Do not propose n8n workflows for ingestion, retrieval, generation, or evaluation. n8n remains valid for unrelated automation outside Uber-RAG.

## Research note template

Use `docs/uber-rag/templates/research_note.md`.

Every research note must include:

- One-paragraph **Bottom Line** in plain language (the user is not a RAG specialist).
- **Sources** with URL, access date, version, tier (1/2/3).
- **Findings** structured by question.
- **Implementation impact** — what changes in the codebase, ADRs, or `STACK_REFERENCES.md`.
- **Open questions** — what remains uncertain.

## Citation discipline (in `STACK_REFERENCES.md`)

Each durable claim must have:

- URL
- Source type (Tier 1 / Tier 2)
- Date accessed
- Version if applicable
- Implementation impact

## Updating references

When a source changes behavior or a dependency version changes:

1. Add a research note dated to the day of discovery.
2. Update `STACK_REFERENCES.md` with the new version pin and access date.
3. Update affected ADRs (or open new ones if the change is material).
4. Update `PROJECT_STATE.md` risks and assumptions.
5. Flag the change at the next phase-entry gate.
