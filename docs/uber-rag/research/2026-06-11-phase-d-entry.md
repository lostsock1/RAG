# Phase D entry note — grounding-verifier candidates (2026-06-11)

Scope: verify licenses, sizes, integration surface, and claimed performance of
grounding-verifier candidates from current primary sources before ADR-0019.
Method note: WebSearch was rate-limited this session; verification used the
Hugging Face model API and raw model-card/repository files directly — these are
the Tier-1 primary sources the protocol prefers anyway.

## Candidates verified (HF model API + cards, 2026-06-11)

| Model | License (card) | Size | Integration | Verdict |
|---|---|---|---|---|
| `lytang/MiniCheck-Flan-T5-Large` | **MIT** | 783M (flan-t5-large) | Plain `transformers` seq2seq — **no `custom_code`** | **Default candidate** |
| `lytang/MiniCheck-RoBERTa-Large` | MIT | 0.4B | Plain sequence classification | Faster fallback (slightly weaker per paper) |
| `bespokelabs/Bespoke-MiniCheck-7B` | **None on card** + `custom_code` (internlm2) | 7B | trust_remote_code required | **Disqualified** (no license; size; custom code) |
| `vectara/hallucination_evaluation_model` (HHEM-2.x) | Apache-2.0 | ~0.1–0.2B | **`custom_code`** (HHEMv2Config → `trust_remote_code=True`) | Rejected for default — same trust_remote_code posture that rejected the minicpm reranker (ADR-0014, CVE-2026-27893 precedent); strong revisit candidate if Vectara ships a standard architecture |
| `ibm-granite/granite-guardian-3.2-3b-a800m` | Apache-2.0 | 3B MoE (800M active) | Generation-style judging (chat template) | GPU-era reopen candidate |
| `ibm-granite/granite-guardian-3.1-2b` | Apache-2.0 | 2B | Generation-style judging | GPU-era reopen candidate |

## MiniCheck-Flan-T5-Large facts (from card + official repo source)

- Paper: *MiniCheck: Efficient Fact-Checking of LLMs on Grounding Documents*
  (EMNLP 2024, arXiv:2404.10774). Card claims: best fact-checking model < 1B on
  the LLM-AggreFact benchmark (11 human-annotated grounding datasets, unseen in
  training), "on par with GPT-4, but 400x cheaper". Sentence-level by design:
  `MiniCheck-Model(document, claim) -> {0, 1}` with raw probability.
- Exact inference recipe (extracted from the official repo,
  `minicheck/inference.py`, MIT):
  - input text: `"predict: " + document + tokenizer.eos_token + claim`,
    max_length 2048, truncation;
  - forward pass with `decoder_input_ids = [[0]]` (single zero token);
  - `label_logits = logits[:, [3, 209]]` (token 3 = unsupported, 209 =
    supported); `P(support) = softmax(label_logits)[1]`;
  - long documents: chunk + max-aggregate (not needed for our per-block scoring
    — context blocks are far below 2048 tokens);
  - multi-sentence claims: the authors recommend splitting claims into
    sentences and aggregating yourself — exactly our existing verifier shape.
- Consequence: implementable with plain `transformers`
  (`AutoModelForSeq2SeqLM`) already in our ML stack — no new dependency, no
  `trust_remote_code`, no git package.

## Decision input for ADR-0019

MiniCheck-Flan-T5-Large is the only candidate that simultaneously satisfies:
commercially-clean license (MIT), no trust_remote_code, CPU-viable size
(783M, same class as the BGE reranker), sentence-level grounding semantics
matching our verifier seam, and benchmark evidence on grounding (not generic
NLI — the failure mode that broke entailment mode in ADR-0016 was generic-NLI
strictness on paraphrase, which MiniCheck's synthetic grounding training
explicitly targets).

Sources (fetched 2026-06-11):
- https://huggingface.co/api/models/lytang/MiniCheck-Flan-T5-Large (license: mit)
- https://huggingface.co/lytang/MiniCheck-Flan-T5-Large (card)
- https://github.com/Liyan06/MiniCheck — `minicheck/inference.py` (recipe)
- https://huggingface.co/api/models/bespokelabs/Bespoke-MiniCheck-7B (license: none)
- https://huggingface.co/api/models/vectara/hallucination_evaluation_model (apache-2.0, custom_code)
- https://huggingface.co/api/models/ibm-granite/granite-guardian-3.2-3b-a800m (apache-2.0)
- arXiv:2404.10774 (MiniCheck, EMNLP 2024)
