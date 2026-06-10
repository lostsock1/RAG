# ADR-0004: LLM Adapter Contract and Default API Provider

Status: Accepted
Date: 2026-05-14
Last updated: 2026-05-15 — provider renamed from OpenRouter to ppq.ai (same concept, OpenAI-compatible aggregator); pricing analysis retained against OpenRouter rates as reference baseline pending ppq.ai confirmation.
Supersedes: ADR-0003 (LLM Selection Benchmark Plan)

## Context

ADR-0003 proposed a local benchmark on 2× RTX 3090 hardware to select an LLM from Llama 3.3 70B, Qwen2.5 32B, and Mistral Small 3.x. That plan is no longer applicable: **no local GPU hardware is currently available**. All LLM calls during development and testing will go through a remote API.

The project needs:
1. An **LLM adapter interface** that decouples the retrieval/generation pipeline from any specific model or provider.
2. A **default API provider and model** for Phase 0–4 testing, chosen from available options based on cost, context window, multilingual quality, and instruction-following.
3. A **clear path to local models** when hardware becomes available — no rewrite required.

The user provided the following model listing for cost analysis (pricing reference accessed via OpenRouter rates 2026-05-14; ppq.ai is an OpenAI-compatible aggregator and exposes the same model IDs — actual ppq.ai prices should be confirmed before SLA commitments):

| Model | ID | Context | Input $/1M | Output $/1M | Date |
|-------|-----|---------|------------|-------------|------|
| Hermes 3 70B Instruct | `nousresearch/hermes-3-llama-3.1-70b` | 131K | $0.32 | $0.32 | Aug 2024 |
| Hermes 4 70B | `nousresearch/hermes-4-70b` | 131K | $0.14 | $0.42 | Aug 2025 |
| Llama 3 70B Instruct | `meta-llama/llama-3-70b-instruct` | 8K | $0.54 | $0.78 | Apr 2024 |
| Llama 3.1 70B Instruct | `meta-llama/llama-3.1-70b-instruct` | 131K | $0.42 | $0.42 | Jul 2024 |
| Llama 3.3 70B Instruct | `meta-llama/llama-3.3-70b-instruct` | 131K | $0.10 | $0.34 | Dec 2024 |
| R1 Distill Llama 70B | `deepseek/deepseek-r1-distill-llama-70b` | 131K | $0.73 | $0.84 | Jan 2025 |

Fine-tunes and specialized variants excluded from analysis — they cost more without compensating gains for RAG generation.

## Decision

### 1. LLM Adapter Contract

All LLM calls go through an **internal OpenAI-compatible API adapter**. The adapter:

- Presents a single interface to the generation service: `chat(messages, **kwargs) → ChatResponse`.
- Accepts a `model` parameter, an `adapter` config key, and standard `temperature`/`max_tokens`.
- Hides provider details (ppq.ai, local vLLM, local llama.cpp) behind the adapter.
- Is configured via environment variables: `LLM_ADAPTER` (`ppq` | `vllm` | `llamacpp`), `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`.

This means:
- Swapping from ppq.ai → local vLLM is a config change, not a code change.
- The generation service never knows which provider is in use.
- Adding a new provider requires only a new adapter module implementing the `LlmBackend` interface.

```
┌──────────────────────────┐
│  Generation Service      │
│  (calls adapter)         │
└─────────┬────────────────┘
          │
    ┌─────▼─────┐
    │  LlmAdapter│   ← interface: chat(messages, **kwargs) → ChatResponse
    └─────┬─────┘
          │
  ┌───────┼───────┐
  │       │       │
  ▼       ▼       ▼
 ppq.ai  vLLM   llama.cpp
 (API)   (local) (local)
```

### 2. Default Provider: ppq.ai

**ppq.ai** is the default API provider for Phase 0–4 testing. Rationale:

- Single API key, single OpenAI-compatible endpoint (`https://api.ppq.ai/v1` — verify exact endpoint on first use).
- Access to a wide range of models, including all candidates listed in the Context table.
- No per-provider integration work. One integration gives us Llama, Qwen, Mistral, DeepSeek, and more via OpenAI-compat shape.
- When local hardware arrives, swap the adapter config — zero code change to retrieval/generation.

### 3. Default Model: Llama 3.3 70B Instruct

**`meta-llama/llama-3.3-70b-instruct`** is the default model. Rationale:

- **Cost**: $0.10 input / $0.34 output per 1M tokens (OpenRouter reference rate; ppq.ai pricing should be confirmed against this baseline) — cheapest of all viable candidates. At ~3,000 tokens per RAG prompt (8 chunks + system prompt + user query) and ~300 token answers, approximately **1,000 queries per dollar** at reference rates.
- **Context window**: 131,072 tokens — ample for 8–20 retrieved passages plus system prompt and chat history.
- **Multilingual**: Meta's December 2024 release. Strong English, solid German and Portuguese (per community reports and multilingual training data composition).
- **Instruction-following**: Same instruction-tuning advances as Llama 3.1 with efficiency improvements. Adequate for citation-disciplined RAG prompts.
- **Latest Meta Instruct**: Newer than Llama 3.1, cheaper, same context window. No reason to pick 3.1 over 3.3.

### 4. Fallback Model: Hermes 4 70B

**`nousresearch/hermes-4-70b`** is the designated fallback for tasks where instruction-following precision is critical (citation formatting, structured JSON output for the verifier). Rationale:

- **Newest** (August 2025) — incorporates post-training advances not in Llama 3.3.
- **Same price point** as Llama 3.3 (~$0.0003 avg per prompt at reference rates).
- **Better structured output** — Hermes models are specifically fine-tuned for function calling and structured generation, which matters for the sentence-level verifier (Stage 1 evidence discipline requires structured verdict output).
- Not the default because it is a fine-tune of an older base (Llama 3.1), and the cost is equivalent — no reason to prefer it for general RAG generation over Llama 3.3's newer base.

### 5. What this replaces

ADR-0003 (LLM Selection Benchmark Plan) is **superseded**. The local benchmark on 2×3090 hardware is deferred until local hardware becomes available. At that point, a new ADR will:
1. Benchmark local candidates (vLLM-served models) against the ppq.ai baseline using the project's eval harness.
2. Select a local model if it matches or beats the API baseline on faithfulness + citation accuracy + cost-at-scale.
3. The adapter makes this a 1-day swap with no pipeline changes.

## Consequences

### Positive

- **No benchmark tax.** Development starts immediately with a known-good, cheap API model.
- **Adapter discipline enforced from day one.** Every LLM call goes through the adapter, so local-model migration is a config change.
- **ppq.ai gives model flexibility.** If Llama 3.3 proves weak on German citation formatting, try Hermes 4 or Qwen 2.5 without any integration work.
- **Cost is negligible for testing.** ~$1 per 1,000 RAG queries at OpenRouter reference rates (ppq.ai prices to be confirmed).
- **One API key, one integration.** No multi-provider complexity.

### Negative

- **API dependency.** No answers without internet. Acceptable for Phase 0–4 testing but must be resolved before production (air-gapped readiness requires local models).
- **No performance measurement yet.** We do not know P50 latency or tokens/sec through ppq.ai. Acceptable for testing; must be measured before production SLAs.
- **ppq.ai is a proxy, not a first-party provider.** Adds an intermediary. Mitigated by the adapter — if ppq.ai has an outage, swap `LLM_BASE_URL` to a direct provider (Together, Groq) or to another OpenAI-compat aggregator (OpenRouter) with the same model ID.
- **Llama 3.3 multilingual quality is unverified** on the project's German/Portuguese corpus. If retrieval eval shows poor multilingual faithfulness, the fallback (Hermes 4) or a new candidate (Qwen 2.5 via ppq.ai) can be tested without architecture changes.
- **ppq.ai actual pricing is not yet confirmed** against the OpenRouter reference table. First production-volume billing cycle should be reconciled with the projected cost-per-query.

## Alternatives considered

- **Run a local model immediately (no hardware)** — rejected. No GPU available. CPU-only inference at 70B parameters is not viable.
- **Direct provider integration (Together, Groq, Anthropic)** — rejected. An OpenAI-compatible aggregator's single-endpoint model access reduces integration surface. Direct providers can be added as additional adapter backends later.
- **OpenRouter as the aggregator** — considered and used as the pricing reference for this ADR. ppq.ai chosen instead per project preference (same concept, OpenAI-compatible). Both aggregators expose equivalent model IDs and OpenAI-compat shape; the analysis is unchanged.
- **Default to Hermes 4 70B instead of Llama 3.3** — rejected. Llama 3.3 is on a newer base model (3.3 vs 3.1) with equivalent cost and broader community validation. Hermes 4 is the better structured-output fallback.
- **Default to a smaller/cheaper model (Llama 3.1 8B, Mistral 7B)** — rejected. 70B-class models are needed for faithful multi-passage synthesis with citation discipline. Smaller models hallucinate more on RAG tasks and cost savings are marginal at testing volumes.
- **Pick without measuring (as ADR-0003 warned against)** — acknowledged. The measurement deferred here is the *production model selection* benchmark. The *testing model* selection is based on cost, context, and capability fit — sufficient for Phase 0–4 development. The production benchmark is a Phase 4 exit criterion.

## References

- ppq.ai (OpenAI-compatible aggregator) — https://ppq.ai (verify exact docs URL on first use)
- OpenRouter pricing reference — https://openrouter.ai/docs (accessed 2026-05-14; used as cost baseline for the Context table)
- OpenRouter model list — provided by user, 2026-05-14
- Llama 3.3 70B Instruct model card — https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct (accessed 2026-05-14)
- Hermes 4 70B — https://huggingface.co/NousResearch/Hermes-4 (accessed 2026-05-14)
- OpenAI chat completions API (compatibility target) — https://platform.openai.com/docs/api-reference/chat (accessed 2026-05-14)
- Internal: `docs/uber-rag/STACK_REFERENCES.md` § LLM serving
- Internal: ADR-0003 (superseded)
- Internal: `docs/uber-rag/ARCHITECTURE.md` § Internal services (generation service)

## Revisit triggers

Reopen this ADR if any of the following occurs:

- **Local GPU hardware becomes available** (2×3090, H100, L40S, or equivalent). Trigger: run the originally-planned benchmark from ADR-0003 against the API baseline. Select local model if it meets the quality + latency thresholds.
- **ppq.ai becomes unavailable or prohibitively expensive** for the project's testing volume. Trigger: add a direct provider adapter (Together, Groq, or Anthropic) or switch to another OpenAI-compat aggregator (OpenRouter, etc.) and update `LLM_BASE_URL`.
- **Actual ppq.ai pricing diverges materially** from the OpenRouter reference rates used in the cost analysis. Trigger: re-run the cost projection and decide whether to switch aggregator.
- **Llama 3.3 70B shows unacceptable faithfulness or multilingual quality** on the project's eval set during Phase 4 testing. Trigger: test Hermes 4 and Qwen 2.5 through ppq.ai; if neither works, escalate to a dedicated ADR.
- **A materially better open-weights model is released** in the 24–80B class with commercial-compatible licensing and ppq.ai availability. Trigger: test against the eval set; supersede if it wins on faithfulness + cost.
- **Air-gapped deployment becomes imminent** (Phase 6). Trigger: the local model benchmark becomes a phase-entry gate.
- **Scheduled reopen (added 2026-06-10):** master plan task E5 runs a structured answering-LLM bake-off as soon as the Phase C measurement rig and Phase D verifier exist — incumbent vs. current open-weight grounded-QA candidates (entry-gate-verified model cards; ~20–120B class), scored on faithfulness, negative-answer compliance, the DE/PT multilingual subset, cost, and local-serving footprint. Decision rule: smallest servable model within 0.02 of the incumbent on quality wins (buys the air-gap path and the ADR-0008 latency lever together). This converts the reactive "materially better model" trigger above into a scheduled, rig-driven check. See `docs/superpowers/plans/2026-06-10-sota-master-plan.md` § E5.
