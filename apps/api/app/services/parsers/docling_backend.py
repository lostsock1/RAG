from __future__ import annotations

from collections.abc import Callable
from importlib import import_module

from app.schemas.parsed_artifacts import ParsedArtifact
from app.services.parsers.base import DocumentParser, ParseRequest


class DoclingDocumentParser(DocumentParser):
    backend_name = "docling"

    def __init__(self, converter: Callable[[ParseRequest], ParsedArtifact] | None = None) -> None:
        self._converter = converter

    def parse(self, request: ParseRequest) -> ParsedArtifact:
        if self._converter is not None:
            artifact = self._converter(request)
            artifact.provenance.parser_backend = self.backend_name
            artifact.provenance.profile = request.profile
            return artifact

        try:
            import_module("docling")
        except ImportError as exc:
            raise RuntimeError(
                "Docling parsing is not configured. Install the docling package or inject a converter before running Phase 2 parsing."
            ) from exc

        raise RuntimeError(
            "Docling is installed, but no converter is wired yet. Inject a converter to enable normalized parsed-artifact generation."
        )
