from __future__ import annotations

from dataclasses import dataclass

from app.schemas.parsed_artifacts import ParsedArtifact


@dataclass(slots=True)
class ParseRequest:
    document_id: str
    object_key: str
    content_type: str
    profile: str
    local_source_path: str | None = None


class DocumentParser:
    backend_name: str

    def parse(self, request: ParseRequest) -> ParsedArtifact:
        raise NotImplementedError
