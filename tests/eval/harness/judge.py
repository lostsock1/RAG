"""LLM-as-judge calibration helpers (master plan D5). EVAL-ONLY — never production.

The judge provides a complementary, non-deterministic reading of per-sentence
support, used to calibrate trust in the cheap production verifier via Cohen's
kappa. Per the Phase C entry note, the judge stays decoupled from production
model choices to avoid evaluator circularity.
"""
from __future__ import annotations

import re

JUDGE_PROMPT = """You are verifying whether a claim is supported by evidence.

Evidence:
{evidence}

Claim: {claim}

Is the claim fully supported by the evidence above? Reply with exactly one word: YES or NO."""


def cohens_kappa(labels_a: list[int], labels_b: list[int]) -> float:
    """Cohen's kappa for two binary label sequences."""
    if len(labels_a) != len(labels_b):
        raise ValueError("label sequences must have equal length")
    if not labels_a:
        raise ValueError("label sequences must be non-empty")
    n = len(labels_a)
    po = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / n
    pa1 = sum(labels_a) / n
    pb1 = sum(labels_b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def split_sentences(text: str) -> list[str]:
    """The verifier family's splitter — judge labels must align with it."""
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


class PpqSentenceJudge:
    """Per-sentence YES/NO support judge over an OpenAI-compatible endpoint."""

    def __init__(self, *, base_url: str, api_key: str, model_name: str, timeout_seconds: float = 30.0) -> None:
        import httpx

        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._timeout = timeout_seconds
        self._client = httpx.Client()

    def judge(self, *, sentence: str, evidence_blocks: list[str]) -> int:
        """1 = supported, 0 = not supported (or unparseable — conservative)."""
        prompt = JUDGE_PROMPT.format(evidence="\n\n".join(evidence_blocks), claim=sentence)
        response = self._client.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model_name,
                "temperature": 0.0,
                "max_tokens": 4,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        text = (
            response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        ).strip().upper()
        return 1 if text.startswith("YES") else 0
