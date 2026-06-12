from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.schemas.chunks import Chunk


@dataclass(frozen=True)
class ContextualizeInput:
    """Everything a contextualizer needs to situate one document's chunks.

    ``document_text`` is the full document text (used by the LLM arm to write
    a chunk-situating context); the breadcrumb arm ignores it and reads only
    structural fields already on each chunk.
    """

    document_title: str
    document_text: str
    leaf_chunks: list[Chunk]


class ChunkContextualizer(Protocol):
    def contextualize(self, payload: ContextualizeInput) -> dict[object, str | None]:
        """Return a situating prefix per leaf chunk, keyed by ``chunk.id``.

        A None or empty value means "no prefix" for that chunk. Chunks absent
        from the returned mapping are left unaugmented.
        """
        ...
