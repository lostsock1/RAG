# Phase C entry note — relevance-labeling methodology (2026-06-10)

Scope (deliberately narrow per the master plan): confirm current best practice for
LLM-assisted graded relevance labeling before C5 scales the heldout set. Nothing
else new is being adopted in Phase C.

## What was checked

- **UMBRELA** (arXiv:2406.06519) — open-source reproduction of Bing's LLM relevance
  assessor; the tool used by the TREC 2024 RAG track for LLM-based qrels. (Tier 1:
  primary paper + official tooling.)
- **TREC 2024 RAG large-scale study** (arXiv:2411.08275; SIGIR/ICTIR follow-up
  10.1145/3731120.3744605) — compared four assessment regimes (fully manual NIST,
  fully automatic UMBRELA, LLM-prefiltered pools, human-edited LLM labels) across
  77 runs / 19 teams. Finding: **run-level system rankings from UMBRELA judgments
  correlate highly with fully manual rankings**; hybrid human-post-edit regimes
  showed no clear benefit over fully automatic. (Tier 1.)
- **Clarke & Dietz et al.** (arXiv:2412.17156, EVIA 2025) — counterpoint: LLM-based
  assessment **cannot fully replace** human judgment; known failure modes include
  prompt sensitivity and circularity/manipulation risk when the judge model is
  public and systems optimize against it. (Tier 1 paper, cautionary.)

## Decision for this project

1. **Primary ground truth stays span-anchored, not label-anchored.** Our fixture
   corpora are authored, so the relevant evidence is *known at authoring time* —
   each question carries verbatim evidence spans; relevant chunk IDs are resolved
   at eval time by exact substring match against the ingested chunks. This is
   stronger than any assessor (human or LLM) and immune to judge drift. It also
   survives re-chunking (content-anchored, not index-anchored) and fails loudly
   when a span stops matching (ground-truth rot guard).
2. **LLM-assisted labeling is approved for C5 scale-out in the UMBRELA pattern**,
   restricted to: (a) drafting candidate spans/labels for *new* authored documents,
   and (b) auditing — flagging retrieved-but-unlabeled chunks that might be
   relevant (pool expansion). Every LLM-drafted label gets a human (session-owner)
   spot-check before commit; the committed YAML is the source of truth, never live
   LLM judgments.
3. **The faithfulness judge and the retrieval qrels stay decoupled** from any
   production model choice to avoid the circularity risk Clarke et al. flag
   (relevant later for master plan D5/E5).

## C5 outcome note (2026-06-11)

Scaled the evidence-backed set from 15 to **60** questions by authoring 8 new
fixture documents (16 total), including 2 German and 2 Portuguese docs, and
backfilling span-anchored evidence for previously-skeletal questions. All spans
verified verbatim before commit; no LLM labeling was needed at this scale because
the fixtures are authored (the UMBRELA-pattern assistance from the methodology
above is held for a future, larger, non-authored corpus).

Multilingual finding (retrieval-only, BGE-M3 dense): **German and Portuguese
subsets score recall@10 = nDCG@10 = MRR@10 = 1.000** (n=7 each) — the
"multilingual quality unverified" open risk is materially reduced for *retrieval*
(generation quality in DE/PT is a separate, still-open question for Phase D/E5).

**Honest caveat — the corpus is currently easy.** recall@10 = 1.000 and
nDCG@10 = 0.944 at 60 questions reflect a corpus of topically *distinct*
documents: each question's evidence lives in one obviously-matching doc, so dense
retrieval rarely has to discriminate between confusable passages. This is a
ceiling artifact, not proof the retriever is excellent. Two consequences: (1) the
measured weakness is *ranking* (5 questions place first-relevant beyond rank 3),
not recall, so contextual augmentation (E2, recall-oriented) cannot show a win on
this corpus and must be evaluated on a harder one; (2) a future eval-corpus task
should add near-duplicate / same-topic / distractor documents so recall@k has
headroom to move. Logged for Phase E planning.

Sources:
- [UMBRELA (arXiv:2406.06519)](https://arxiv.org/pdf/2406.06519)
- [A Large-Scale Study of Relevance Assessments with LLMs (arXiv:2411.08275)](https://arxiv.org/pdf/2411.08275)
- [Follow-up study (ACM)](https://dl.acm.org/doi/pdf/10.1145/3731120.3744605)
- [LLM-based relevance assessment still can't replace human assessment (arXiv:2412.17156)](https://arxiv.org/html/2412.17156v1)
