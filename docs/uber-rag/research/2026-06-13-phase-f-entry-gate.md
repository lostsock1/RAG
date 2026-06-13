# Phase F entry note — book profile + frontend E2E (2026-06-13)

Status: Verified

Scope: the three Phase F entry-gate questions from the master plan —
(1) Docling current release + heading/page-anchor extraction fidelity for the
book-profile chunker; (2) Next.js / App Router stability for the frontend build;
(3) Playwright vs Cypress for the E2E rig. Plus one repo-grounding pass per
question, because the gate's job is to catch drift between the plan's assumptions
(written 2026-06-10) and current reality.

Method note: live research via WebFetch on Tier-1 primary sources (Docling GitHub
releases + docs, Next.js official upgrade guide + release blog) and WebSearch for
the comparative Playwright/Cypress question, cross-checked against what the repo
actually pins and runs. Access date 2026-06-13 throughout.

## Bottom Line

All three gate questions resolve cleanly, but two carry a surprise the plan did
not assume. **(1) Docling** is healthy and current (v2.102.1, released the day
before this note) and its `DoclingDocument` model exposes exactly the chapter →
section → heading hierarchy and per-item page anchors the book profile needs —
**but the repo's existing Docling adapter throws all of that away** (it emits flat
pages + tables, `blocks=[]`), and Docling is not even pinned or installed. So F1 is
larger than "write a book chunker": it must first pin Docling and extend the
adapter to surface hierarchy. **(2) Next.js**: the repo pins `^15.3`, but the
current stable is **16.2.x** (16 went stable Oct 2025). The frontend is still only
three pages with `node_modules` absent, so upgrading to 16 now — running the
official codemod, renaming the trivial `middleware.ts` to `proxy.ts` — is near-free
and avoids retrofitting async-params/proxy changes after F3 builds the chat UI.
**Recommend adopting Next.js 16 at the start of F3.** **(3) Playwright** wins
decisively (≈45% vs ≈14% adoption, free native CI parallelization that fits the
air-gapped/self-hosted invariant, ~10 MB vs ~500 MB footprint); the plan's "pick
Playwright unless evidence says otherwise" is confirmed.

---

## Q1 — Docling: current release + book-hierarchy/page-anchor fidelity

### Sources
- Docling releases: https://github.com/docling-project/docling/releases · Accessed 2026-06-13 · Reliability: repo (official)
- DoclingDocument data model: https://docling-project.github.io/docling/concepts/docling_document/ · Accessed 2026-06-13 · Reliability: official docs

### Findings
- **Latest release v2.102.1 (2026-06-12)** — one day before this note; the line is
  extremely active (v2.100.0 → v2.102.1 across 2026-06-09…06-12). Still the v2
  series — **no v3 breaking re-architecture pending**. Recent notable items:
  `v2.100.0` added an **EPUB document backend with full conversion support** (and a
  DocLang backend); `v2.101.0` added `generate_page_images` control; `v2.102.x` are
  service/artifact-retrieval features + an `image_export_mode` default fix. None
  touch the hierarchy/page-anchor data model — it is stable.
- **The `DoclingDocument` model exposes the book profile's structural needs
  directly:**
  - `body` — tree root for main content; reading order is encoded by the order of
    each item's `children`.
  - `groups` — container nodes (lists, **chapters**) that nest contained items.
  - `texts` — paragraphs, **headings (incl. section headers)**, equations; all
    inherit from `TextItem`/`DocItem`.
  - `tables`, `pictures` — with optional structure annotations (matches the
    loose-profile atomic-table handling).
  - `furniture` — headers/footers and non-body items (so running heads can be
    excluded from chunk text).
  - **`prov` on every item** — page anchors + bounding boxes tied to source
    location. This is the per-leaf `page_start`/`page_end` the plan needs to flow
    into citations.
  - Parent/child references are JSON pointers → programmatic tree traversal;
    `DoclingDocument.iterate_items()` walks body/groups/furniture in reading order.
- This squares with ADR-0012, which already specifies walking the
  `DoclingDocument` body tree at structural boundaries and keeping a heading path
  per chunk. The model has not regressed since that ADR.

### Repo-grounding finding (the surprise)
- **Docling is NOT pinned in `pyproject.toml` and NOT installed** (`import docling`
  fails on this machine; no parser/OCR deps are declared). The backend
  (`apps/api/app/services/parsers/docling_backend.py`) imports it lazily via
  `import_module("docling.document_converter")` and otherwise runs an injected test
  converter — so **Docling has never actually executed in this repo**; every test
  uses a double.
- **The adapter discards hierarchy.** `_normalize_docling_result` maps only
  `document.pages` (reduced to `export_to_markdown()` per page) and
  `document.tables`; every `ParsedPage` is emitted with `blocks=[]`. It never reads
  `body`, `groups`, `texts`, or per-item `prov`. The exact chapter/section/heading
  tree and per-item page anchors the book chunker depends on are available from
  Docling and dropped on the floor today.

### Implementation impact (F1)
F1 is "book chunker" **plus** two prerequisites the plan did not separate out:
1. **Pin + install Docling** (`docling>=2.102,<3` — pin the major to avoid a future
   v3 surprise) with a `STACK_REFERENCES.md` entry per the change-discipline rule,
   and confirm CPU model download/cold-start cost on the VPS (consistent with the
   freeze: Docling runs on CPU, no API).
2. **Extend the parser adapter to surface hierarchy**: emit a structured
   representation (heading path, item type, page anchor via `prov`, bbox) by
   iterating the `DoclingDocument` body tree — not just flat page markdown.
   `ParsedPage.blocks` is the empty seam already present for this.
3. Then the book chunker (`services/chunkers/book.py`) consumes that structure:
   chapter → section → leaf, heading-path breadcrumbs (these are what make E2's
   breadcrumb mode finally have signal on books), atomic tables/figures, page
   anchors into chunk metadata → citations gain page numbers.
Acceptance still uses a small public-domain textbook PDF fixture, but it now
exercises **real Docling** for the first time — so the fixture test is also the
first proof the adapter works end to end, not just the chunker.

---

## Q2 — Next.js / App Router stability

### Sources
- Next.js 16 upgrade guide: https://nextjs.org/docs/app/guides/upgrading/version-16 · Accessed 2026-06-13 · Version: docs at 16.2.9 (lastUpdated 2026-05-13) · Reliability: official docs
- Next.js 16 release blog: https://nextjs.org/blog/next-16 · Published 2025-10-21 · Accessed 2026-06-13 · Reliability: official
- "Next.js App Router in 2026: Is It Ready for Production?" — https://meisteritsystems.com/news/next-js-app-router-in-2026-is-it-ready-for-production/ · Accessed 2026-06-13 · Reliability: secondary
- Current-version reference (16.2.7 stable, June 2026) — https://www.abhs.in/blog/nextjs-current-version-march-2026-stable-release-whats-new · Accessed 2026-06-13 · Reliability: secondary

### Findings
- **App Router is the production default** and `create-next-app` ships it by
  default. No stability concern for new App-Router work.
- **Current stable is Next.js 16.2.x; Next.js 16 went stable 2025-10-21.** The repo
  pins `next: ^15.3` (one major behind) and `react/react-dom: ^19.1`. React 19 is
  GA; Next 16's App Router tracks React 19.2 canary features (View Transitions,
  `useEffectEvent`, `<Activity>`) — non-blocking for us.
- **Next.js 16 changes that touch THIS repo's frontend** (verified against the
  actual files — `apps/web/` is `app/{login,upload,documents}/page.tsx`, `layout.tsx`,
  2 components, `lib/api-client.ts`, `middleware.ts`, `next.config.js`):
  - **Async request APIs fully enforced** — `params`/`searchParams`/`cookies()`/
    `headers()` must be awaited (the temporary sync shim from 15 is gone). The
    login page reads `searchParams.next` → becomes `await props.searchParams`.
    Trivial at 3 pages; painful once F3 adds chat + ACL editor. `next typegen`
    generates `PageProps`/`LayoutProps` helpers for type-safe migration.
  - **`middleware.ts` → `proxy.ts`** (Node.js runtime; edge not supported under
    `proxy`). The repo's middleware is a **synchronous cookie-presence redirect
    guard with no edge runtime and no `next/headers` imports** — migration is a
    file rename + function rename `middleware`→`proxy`; `request.cookies` is
    unchanged. Clean.
  - **`next lint` removed** — `package.json` has `"lint": "next lint"`, which breaks
    on 16; switch to the ESLint CLI (codemod `next-lint-to-eslint-cli` automates it).
  - **Turbopack is the default bundler** (2–5× faster builds, up to 10× Fast
    Refresh) — a CI win for F3/F4. `next.config.js` turbopack options move to
    top-level (codemod handles it).
  - Minimums: **Node 20.9+**, **TypeScript 5.1+** — repo pins TS `^5.8` (fine);
    confirm the CI/dev Node is ≥ 20.9.
  - PPR/`cacheComponents`, `revalidateTag` signature, `next/image` defaults — not
    used by the current pages; irrelevant now.
- The official **`@next/codemod@canary upgrade latest`** automates config,
  lint-CLI, middleware→proxy, and `unstable_`-prefix removals; a Next.js DevTools
  MCP exists for agent-assisted migration.

### Recommendation (F3)
**Adopt Next.js 16 at the start of F3**, before building the chat UI / ACL editor.
Rationale: (a) the frontend surface is three pages with `node_modules` absent, so
F3 already begins with a clean `npm ci` — folding in `next@latest react@latest
react-dom@latest` + the codemod costs near-nothing now; (b) the only non-cosmetic
changes (async params, middleware→proxy, lint CLI) are each one-liners at this size
and grow with every page added; (c) "best possible outcome / SOTA" means not
shipping a brand-new frontend already a major version behind. This is a version
bump within an accepted stack (Next.js), **not a stack swap** — no ADR/benchmark
gate under DEVELOPMENT_RULES — but it revises the F3 task scope, so it is recorded
here and threaded into the plan for the planner/user to confirm. If declined,
15.3 remains production-supported and Phase F can proceed on it; the cost is paying
the same migration later against a larger surface.

---

## Q3 — Playwright vs Cypress for the E2E rig

### Sources
- "Cypress vs Playwright in 2026" — https://bugbug.io/blog/test-automation-tools/cypress-vs-playwright/ · Accessed 2026-06-13 · Reliability: secondary
- "Cypress vs Playwright 2026: 5x Download Gap…" — https://tech-insider.org/cypress-vs-playwright-2026/ · Accessed 2026-06-13 · Reliability: secondary
- "Playwright vs Cypress in 2026: Guide for Lean Teams" (Autonoma) — https://getautonoma.com/blog/playwright-vs-cypress · Accessed 2026-06-13 · Reliability: secondary
- Playwright docs (canonical, for implementation): https://playwright.dev/docs/intro · Accessed 2026-06-13 · Reliability: official

### Findings
- **Adoption / momentum**: Playwright ≈45.1% vs Cypress ≈14.4%; ~33M vs ~6.5M
  weekly npm downloads. Playwright is the default for new cross-browser projects.
- **Speed / footprint**: Playwright ~290 ms/action vs Cypress ~420 ms; ~2× faster
  headless; ~10 MB vs ~500 MB install → faster CI cold start; ~2.1 GB vs ~3.2 GB
  RAM for 10 parallel tests.
- **CI / parallelization (decisive here)**: Playwright has **free native
  parallelization across workers on any self-hosted CI** (GitHub Actions, Jenkins)
  with no external service. Cypress needs the paid **Cypress Cloud** dashboard for
  reliable parallelism, scaling per-user/per-stream. This is not just cost — it is
  an **architecture-invariant fit**: Uber-RAG targets air-gapped/self-hosted
  deployment; an E2E rig that needs a SaaS dashboard to parallelize is the wrong
  posture. Playwright keeps everything in-cluster.
- **Language reach**: Playwright supports TS/JS/Python/C#/Java — a latent bonus
  given the Python backend (a future API-level E2E could share a language), though
  F4 is TS/JS either way.
- Cypress's edge is interactive DX for frontend-only teams; not decisive for a
  one-happy-path + one-ACL-spec CI suite.

### Decision
**Playwright** — confirmed, resolves the "pending" marker in `STACK_REFERENCES.md`.
F4 runs it against the compose stack (`AUTH_MODE=dev`, stub LLM, seeded fixture
corpus), specs waiting on API state (not timeouts), `retries=1`. Two specs:
happy-path (login → upload → ingest complete → ask → streamed answer + citation →
source viewer) and ACL (Bob cannot see Alice's doc in the UI).

---

## Open questions / follow-ups
- **Docling on the VPS**: confirm CPU cold-start + model-download size for the
  parser pipeline (the freeze keeps it CPU/local). Measure when F1 lands real
  parsing; record alongside the existing BGE-M3 CPU numbers.
- **Public-domain textbook fixture**: pick a small excerpt with genuine chapter →
  section → subsection depth, ≥1 table, and page numbers, that does **not** contain
  any heldout evidence span verbatim (corpus span-isolation invariant). A few pages
  of a Gutenberg/openstax-style text is enough.
- **Next.js 16 decision**: planner/user to confirm the F3-start bump (recommended
  above). If confirmed, add a one-line `STACK_REFERENCES.md` version note (already
  drafted there) — still not a stack swap, so no ADR.
- **EPUB**: Docling's new EPUB backend (v2.100.0) may matter for the book profile's
  loose↔book boundary; out of F1 scope, noted for F2 profile routing.
