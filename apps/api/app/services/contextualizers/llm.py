from __future__ import annotations

import logging

import httpx

from app.services.contextualizers.base import ContextualizeInput

logger = logging.getLogger(__name__)

# Verified against Anthropic's Contextual Retrieval recipe (accessed
# 2026-06-11, https://www.anthropic.com/news/contextual-retrieval): one LLM
# call per chunk, whole document in context, asking for a short (50-100 token)
# situating context to prepend before embedding and BM25 indexing.
_PROMPT_TEMPLATE = """<document>
{document}
</document>
Here is the chunk we want to situate within the whole document:
<chunk>
{chunk}
</chunk>
Please give a short, succinct context (one or two sentences) to situate this \
chunk within the overall document for the purposes of improving search \
retrieval of the chunk. Respond ONLY with the succinct context and nothing \
else."""


class LlmChunkContextualizer:
    """LLM-generated chunk-situating context (Anthropic Contextual Retrieval).

    One completion per leaf chunk via the same OpenAI-compatible provider as
    the answer LLM (ppq.ai / any local server later — air-gap compatible). The
    generated prefix is persisted with the chunk, so the per-chunk ingest cost
    is paid once and is idempotent on re-ingest.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        max_output_tokens: int = 128,
        temperature: float = 0.0,
        document_char_budget: int = 12000,
        transport: object | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._document_char_budget = document_char_budget
        self._transport = transport or httpx.Client()
        self._timeout_seconds = timeout_seconds

    def contextualize(self, payload: ContextualizeInput) -> dict[object, str | None]:
        document = payload.document_text[: self._document_char_budget]
        result: dict[object, str | None] = {}
        for chunk in payload.leaf_chunks:
            if chunk.id is None:
                continue
            prompt = _PROMPT_TEMPLATE.format(document=document, chunk=chunk.text)
            result[chunk.id] = self._complete(prompt)
        return result

    def _complete(self, prompt: str) -> str | None:
        response = self._transport.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model_name,
                "temperature": self._temperature,
                "max_tokens": self._max_output_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            return None
        text = (choices[0].get("message", {}).get("content") or "").strip()
        return text or None
