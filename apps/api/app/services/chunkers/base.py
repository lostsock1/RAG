from __future__ import annotations

from typing import Protocol

from app.schemas.chunks import Chunk, DocumentProfile
from app.schemas.parsed_artifacts import ParsedArtifact


class Chunker(Protocol):
    def chunk(
        self,
        artifact: ParsedArtifact,
        *,
        profile: DocumentProfile,
    ) -> list[Chunk]:
        """Split a parsed artifact into chunks with parent-child relationships.

        Must be deterministic: same input always produces same output.
        """
        ...
