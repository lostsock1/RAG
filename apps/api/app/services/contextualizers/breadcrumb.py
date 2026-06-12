from __future__ import annotations

from app.services.contextualizers.base import ContextualizeInput


class BreadcrumbContextualizer:
    """No-LLM contextualizer: prefix = document title + heading path + page.

    For structured documents this captures much of the contextual-retrieval
    gain for free (ADR-0020): the embedding and BM25 representations gain the
    document and section the chunk came from, which disambiguates a chunk from
    same-topic chunks in other documents. Freeze-compatible (no model calls).

    Example prefix: ``"Physics Textbook Ch3 Thermodynamics > Entropy (p. 5)"``.
    """

    def contextualize(self, payload: ContextualizeInput) -> dict[object, str | None]:
        title = (payload.document_title or "").strip()
        result: dict[object, str | None] = {}
        for chunk in payload.leaf_chunks:
            if chunk.id is None:
                continue
            parts: list[str] = []
            if title:
                parts.append(title)
            parts.extend(h.strip() for h in chunk.heading_path if h and h.strip())
            crumb = " > ".join(parts)
            page = _page_anchor(chunk.page_start, chunk.page_end)
            if page:
                crumb = f"{crumb} ({page})" if crumb else page
            result[chunk.id] = crumb or None
        return result


def _page_anchor(page_start: int | None, page_end: int | None) -> str:
    if page_start is None:
        return ""
    if page_end is not None and page_end != page_start:
        return f"pp. {page_start}-{page_end}"
    return f"p. {page_start}"
