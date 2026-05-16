# ADR-0003: LLM Selection — Benchmark Plan (Not Yet Closed)

Status: Superseded
Date: 2026-05-14
Superseded by: ADR-0004 (LLM Adapter Contract and Default API Provider)

## Context

`STACK_REFERENCES.md` currently lists **Llama 3.3 70B** as the default LLM, served via vLLM or llama.cpp behind an OpenAI-compatible API on the team's hardware (2× RTX 3090, 24 GB VRAM each, 48 GB total).

This default was chosen by reputation, not by measurement on the actual corpus or hardware. Three concerns:

1. **Hardware fit.** Llama 3.3 70B at INT4 is ~38 GB on disk; at INT8 or higher it does not fit two 3090s comfortably with usable context length. Throughput at INT4 on 2×3090 is single-digit tokens-per-second for long contexts.
2. **Context behavior.** RAG generation depends on faithfully synthesizing 8–20 retrieved passages with citation discipline. Long-context faithfulness is model-specific and is not predicted by MMLU or leaderboard rank.
3. **Multilingual quality.** The corpus includes German, Portuguese, and English. Llama 3.x non-English performance is mixed; Qwen2.5 and Mistral variants are often stronger on certain European languages.

The right LLM is whichever wins the project's own retrieval-answer evaluation, not whichever leads a public leaderboard.

This ADR is **Proposed**, not **Accepted**. It defines the benchmark that closes the decision; it does not yet close it.

## Decision (provisional, to be confirmed by benchmark)

Until benchmarks are run, treat Llama 3.3 70B as a **candidate, not a default**. Reclassify in `STACK_REFERENCES.md` to a candidate alongside:

- **Qwen2.5-32B-Instruct** — strong multilingual; fits 2×3090 at FP8 or INT8 with usable context.
- **Mistral-Small-3.x-Instruct** (~24B) — fast, recent, fits 2×3090 with headroom for larger batches.
- **Llama-3.3-70B-Instruct** — strong English; heavy on hardware.

After benchmarks, this ADR closes via a successor ADR (ADR-0004) naming the chosen model.

## Benchmark plan

### Hardware

- 2× RTX 3090 (24 GB each), NVLink if available, otherwise PCIe.
- Serving: vLLM 0.6.x or later, FP8 where supported, otherwise INT8 / GPTQ.
- Concurrency tested at 1, 4, and 16 simultaneous requests.

### Test corpus

A held-out evaluation set drawn from the planned corpus:

- 50 textbook questions (factual lookup, definition recall, multi-paragraph synthesis, formula reference).
- 50 loose-document questions (policy/procedure lookup, version-specific facts, table lookup).
- 20 needle-in-haystack questions (rare term, single occurrence, deep in the corpus).
- 20 negative-answer questions (answer not in the corpus — model must say "insufficient evidence in the indexed sources").
- 20 multilingual questions (German, Portuguese, mixed — query in one language, source in another).

Each question paired with ground-truth retrieved chunks and a reference answer.

### Metrics

Per model:

1. **Faithfulness** — fraction of answer sentences supported by retrieved chunks (sentence-level NLI evaluator, manually spot-checked).
2. **Citation accuracy** — fraction of cited chunks that actually contain the cited fact.
3. **Negative-answer compliance** — fraction of "not in corpus" questions correctly refused without fabrication.
4. **Multilingual quality** — same metrics, segmented by language.
5. **Throughput** — tokens/sec at concurrency 1, 4, 16.
6. **P50 / P99 latency** — time-to-first-token and total response time at concurrency 4.
7. **VRAM headroom** — usable context length under realistic batch sizes.

### Decision rule

Win on **faithfulness + citation accuracy + negative-answer compliance**, subject to:

- P50 latency ≤ 8 seconds for typical 8-chunk context.
- Throughput ≥ 15 tokens/sec at concurrency 1.
- Multilingual scores within 10 % of best for German and Portuguese.

If two models tie within 3 % on quality, choose the smaller/faster one. Lean wins ties.

If no candidate meets the latency/throughput floor, escalate: consider hardware upgrade, smaller candidates (Qwen2.5-14B, Mistral-7B-Instruct), or external LLM API as a transitional measure.

## Consequences

### Positive

- LLM choice is defensible by measurement, not reputation.
- The eval harness built for this benchmark becomes the ongoing model-regression harness — every model swap reruns these tests.
- Forces the team to write eval datasets and retrieval ground truth before generation matters, which is the right order.

### Negative

- Delays the "first end-to-end answer" milestone by 2–3 weeks while the eval harness and held-out set are built.
- Requires careful held-out construction so the benchmark is not gamed by overfitting prompts.

## Alternatives considered

- **Pick Llama 3.3 70B without benchmark** — rejected. Hardware fit and multilingual concerns are real; the cost of a wrong default is high (rewriting prompts, re-tuning, possibly re-architecting context size).
- **Use only a public benchmark (MMLU, MT-Bench, MMLU-Pro)** — rejected. Public benchmarks do not measure RAG faithfulness on the project's corpus or languages.
- **Defer LLM choice until later** — rejected. The eval harness is needed regardless; cheaper to build now while there is no implementation inertia.

## Revisit triggers

This ADR auto-closes when:

- Benchmark results are recorded in `docs/uber-rag/research/YYYY-MM-DD-llm-benchmark.md`.
- A follow-up ADR (ADR-0004) is created with status `Accepted` naming the chosen model.

After closure, reopen if:

- A materially better open-weights model is released (parameter class ~24–80B, license compatible with commercial use).
- The eval set is expanded to a domain not represented in the initial 160 questions.
- Hardware changes (e.g., upgrade to H100 / L40S / 4×3090).

## References

- vLLM documentation — https://docs.vllm.ai/ (accessed 2026-05-14)
- Llama 3.3 model card — https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct (accessed 2026-05-14)
- Qwen2.5 model card — https://huggingface.co/Qwen/Qwen2.5-32B-Instruct (accessed 2026-05-14)
- Mistral Small model family — https://huggingface.co/mistralai (accessed 2026-05-14; researcher to confirm current 3.x version at benchmark time)
- Internal: `docs/uber-rag/EVALUATION_PLAN.md`
- Internal: `docs/uber-rag/STACK_REFERENCES.md` § LLM serving
