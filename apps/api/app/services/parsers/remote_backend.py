from __future__ import annotations

from collections.abc import Callable

import httpx
from pydantic import ValidationError

from app.schemas.parsed_artifacts import ParsedArtifact
from app.services.parsers.base import DocumentParser, ParseRequest


class RemoteDocumentParser(DocumentParser):
    backend_name = "remote-api"

    def __init__(
        self,
        invoke_remote_parser: Callable[[ParseRequest], ParsedArtifact] | None = None,
        *,
        endpoint_url: str | None = None,
        transport: object | None = None,
        timeout_seconds: float = 30.0,
        api_key: str | None = None,
    ) -> None:
        self._invoke_remote_parser = invoke_remote_parser
        self._endpoint_url = endpoint_url
        self._transport = transport or httpx.Client()
        self._timeout_seconds = timeout_seconds
        self._api_key = api_key

    def parse(self, request: ParseRequest) -> ParsedArtifact:
        artifact = (
            self._invoke_remote_parser(request)
            if self._invoke_remote_parser is not None
            else self._parse_via_http(request)
        )
        artifact.provenance.parser_backend = request.parser_backend or self.backend_name
        artifact.provenance.profile = request.profile
        return artifact

    def _parse_via_http(self, request: ParseRequest) -> ParsedArtifact:
        if not self._endpoint_url:
            raise RuntimeError(
                "Remote document parsing is not configured: set REMOTE_PARSER_URL when parser_profile='remote-api'."
            )

        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        try:
            response = self._transport.post(
                self._endpoint_url,
                json={
                    "document_id": request.document_id,
                    "object_key": request.object_key,
                    "content_type": request.content_type,
                    "profile": request.profile,
                    "parser_backend": request.parser_backend or self.backend_name,
                    "local_source_path": request.local_source_path,
                },
                headers=headers,
                timeout=self._timeout_seconds,
            )
            if response.status_code >= 400:
                response.raise_for_status()
            return ParsedArtifact.model_validate(response.json())
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip() or "remote parser service returned an empty error response"
            raise RuntimeError(
                "Remote document parsing failed: the remote parser service returned "
                f"HTTP {exc.response.status_code}. Response: {detail}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(
                "Remote document parsing failed: the remote parser service could not be reached. "
                "Check REMOTE_PARSER_URL and remote parser availability. "
                f"Transport error: {exc}"
            ) from exc
        except ValidationError as exc:
            raise RuntimeError(
                "Remote document parsing failed: the remote parser response did not match the expected artifact schema. "
                "Check the remote parser contract and returned provenance fields."
            ) from exc
