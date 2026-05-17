from __future__ import annotations

from typing import Literal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.schemas.parsed_artifacts import ParsedArtifact
from app.services.parsers.base import ParseRequest


class OcrResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["applied", "not-applied", "unverified"]
    applied: bool | None = None
    engine: str
    provider: str
    page_numbers: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.page_numbers)


class OcrService(Protocol):
    def inspect(self, *, request: ParseRequest, artifact: ParsedArtifact) -> OcrResult: ...


class StubOcrService:
    def __init__(self, result: OcrResult) -> None:
        self._result = result

    def inspect(self, *, request: ParseRequest, artifact: ParsedArtifact) -> OcrResult:
        return self._result.model_copy(deep=True)


class DoclingOcrService:
    def __init__(self, *, engine: str = "tesseract", provider: str = "docling-local") -> None:
        self._engine = engine
        self._provider = provider

    def inspect(self, *, request: ParseRequest, artifact: ParsedArtifact) -> OcrResult:
        return OcrResult(
            status="unverified",
            applied=None,
            engine=self._engine,
            provider=self._provider,
            notes=["OCR usage is not yet verified from the parser runtime output."],
        )


def build_ocr_service(settings: Settings) -> OcrService:
    if settings.parser_profile == "remote-api" or settings.parser_backend in {"remote", "remote-api"}:
        return DoclingOcrService(engine="remote-service", provider="remote-api")

    return DoclingOcrService(engine=settings.ocr_engine, provider="docling-local")
