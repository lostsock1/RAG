from __future__ import annotations

from collections.abc import Callable

from app.schemas.parsed_artifacts import ParsedArtifact
from app.services.parsers.base import DocumentParser, ParseRequest


class RemoteDocumentParser(DocumentParser):
    backend_name = "remote"

    def __init__(self, invoke_remote_parser: Callable[[ParseRequest], ParsedArtifact]) -> None:
        self._invoke_remote_parser = invoke_remote_parser

    def parse(self, request: ParseRequest) -> ParsedArtifact:
        artifact = self._invoke_remote_parser(request)
        artifact.provenance.parser_backend = self.backend_name
        artifact.provenance.profile = request.profile
        return artifact
