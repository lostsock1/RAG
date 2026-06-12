"""Query understanding — route-gated retrieval query expansion (ADR-0021).

A ``QueryUnderstander`` produces ADDITIONAL retrieval queries for a user
query (never echoing the original); the hybrid retriever runs every query
through lexical+dense+sparse retrieval and merges all rank lists through the
existing RRF fusion, then reranks against the ORIGINAL query. Expansion
never runs on exact/quoted routes (ADR-0008 latency discipline) and the
``disabled`` path is byte-identical to the single-query pipeline.
"""
from __future__ import annotations

import logging
import re
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class QueryUnderstander(Protocol):
    def expand(self, query: str) -> list[str]:
        """Return additional retrieval queries for ``query``.

        The original query is never included; an empty list means "no
        expansion". Callers cap and dedupe — implementations should still
        return clean, ordered, non-empty strings.
        """
        ...


class StubQueryExpander:
    """Deterministic expander for tests — no model, no network."""

    def __init__(self, suffixes: tuple[str, ...] = ("rephrased one", "rephrased two")) -> None:
        self._suffixes = suffixes

    def expand(self, query: str) -> list[str]:
        return [f"{query} {suffix}" for suffix in self._suffixes]


# Anchored, deliberately narrow multi-hop shapes (ADR-0021 decompose arm).
# Under-triggering is the accepted trade: a miss costs nothing, a bad split
# pollutes the fusion pool.
_DIFFERENCE_BETWEEN = re.compile(
    r"\bdifference\s+between\s+(.+?)\s+and\s+(.+?)[?.!]?$", re.IGNORECASE
)
_COMPARE = re.compile(
    r"\bcompare\s+(.+?)\s+(?:and|with|to)\s+(.+?)[?.!]?$", re.IGNORECASE
)
_VERSUS = re.compile(r"^(.+?)\s+(?:vs\.?|versus)\s+(.+?)[?.!]?$", re.IGNORECASE)
_TWIN_CLAUSES = re.compile(
    r"^(.{8,}?)\s+and\s+"
    r"((?:what|how|why|when|where|which|who|whose|whom)\b.{4,})$",
    re.IGNORECASE,
)
_MIN_SUBQUERY_CHARS = 3


class HeuristicQueryDecomposer:
    """LLM-free multi-hop decomposition: comparative/two-entity questions
    split into single-entity sub-queries that join the same fusion pool."""

    def expand(self, query: str) -> list[str]:
        normalized = query.strip()
        if not normalized:
            return []
        for pattern in (_DIFFERENCE_BETWEEN, _COMPARE, _VERSUS, _TWIN_CLAUSES):
            match = pattern.search(normalized)
            if match is None:
                continue
            sub_queries = [part.strip() for part in match.groups()]
            if all(len(part) >= _MIN_SUBQUERY_CHARS for part in sub_queries):
                return sub_queries
            return []
        return []


_PROMPT_TEMPLATE = """You rewrite search queries for document retrieval. \
Generate {count} alternative phrasings of the question below. Keep every \
rewrite faithful to the original meaning while varying wording. Respond \
ONLY with the {count} rewrites, one per line, no numbering and no \
commentary.

Question: {query}"""

_LINE_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


class LlmMultiQueryExpander:
    """One LLM call per gated search producing N retrieval paraphrases.

    Uses a small OpenAI-compatible client with an injectable transport — the
    ``LlmBackend`` protocol is answer-shaped (requires a ContextPayload), so
    this follows the ADR-0020 contextualizer precedent and shares the
    ``llm_*`` provider settings instead.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        max_expansions: int = 3,
        max_output_tokens: int = 256,
        temperature: float = 0.0,
        transport: object | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._max_expansions = max_expansions
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._transport = transport or httpx.Client()
        self._timeout_seconds = timeout_seconds

    def expand(self, query: str) -> list[str]:
        response = self._transport.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model_name,
                "temperature": self._temperature,
                "max_tokens": self._max_output_tokens,
                "messages": [
                    {
                        "role": "user",
                        "content": _PROMPT_TEMPLATE.format(
                            count=self._max_expansions, query=query
                        ),
                    }
                ],
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            return []
        content = (choices[0].get("message", {}).get("content") or "").strip()
        return self._parse_rewrites(content, original=query)

    def _parse_rewrites(self, content: str, *, original: str) -> list[str]:
        seen = {original.strip().lower()}
        rewrites: list[str] = []
        for line in content.splitlines():
            rewrite = _LINE_PREFIX.sub("", line).strip().strip('"').strip()
            if not rewrite or rewrite.lower() in seen:
                continue
            seen.add(rewrite.lower())
            rewrites.append(rewrite)
            if len(rewrites) >= self._max_expansions:
                break
        return rewrites


class CompositeQueryUnderstander:
    """Union of several understanders ("both" arm): order-preserving,
    deduplicated against the original and each other, capped."""

    def __init__(self, *, understanders: list[QueryUnderstander], max_expansions: int = 3) -> None:
        self._understanders = understanders
        self._max_expansions = max_expansions

    def expand(self, query: str) -> list[str]:
        seen = {query.strip().lower()}
        merged: list[str] = []
        for understander in self._understanders:
            for rewrite in understander.expand(query):
                normalized = rewrite.strip()
                if not normalized or normalized.lower() in seen:
                    continue
                seen.add(normalized.lower())
                merged.append(normalized)
                if len(merged) >= self._max_expansions:
                    return merged
        return merged


__all__ = [
    "QueryUnderstander",
    "StubQueryExpander",
    "HeuristicQueryDecomposer",
    "LlmMultiQueryExpander",
    "CompositeQueryUnderstander",
]
