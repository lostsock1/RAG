from __future__ import annotations

from app.schemas.chunks import DocumentProfile
from app.services.chunkers.base import Chunker
from app.services.chunkers.book import BookDocumentChunker
from app.services.chunkers.loose import LooseDocumentChunker


def build_chunker(profile: DocumentProfile) -> Chunker:
    """Select the chunker for a document profile (ADR-0012).

    Book documents get the hierarchy-aware chunker; everything else (loose
    documents) gets the structure-aware flat chunker. Both satisfy the
    ``Chunker`` protocol, so the pipeline calls them identically.
    """
    if profile == DocumentProfile.BOOK:
        return BookDocumentChunker()
    return LooseDocumentChunker()
