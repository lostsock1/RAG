from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.parsed_artifacts import ParsedArtifact


class QualityReportSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_score: float
    parser_backend: str
    summary: dict[str, int]
    warnings: list[str]

    @property
    def page_count(self) -> int:
        return self.summary["page_count"]

    @property
    def table_count(self) -> int:
        return self.summary["table_count"]


def build_quality_report(artifact: ParsedArtifact) -> QualityReportSummary:
    page_count = len(artifact.pages)
    table_count = len(artifact.tables)
    non_empty_text_pages = sum(1 for page in artifact.pages if page.text.strip())
    quality_score = 0.0 if page_count == 0 else non_empty_text_pages / page_count
    warnings: list[str] = []

    if non_empty_text_pages != page_count:
        warnings.append("Some pages do not contain extractable text.")

    return QualityReportSummary(
        quality_score=quality_score,
        parser_backend=artifact.provenance.parser_backend,
        summary={
            "page_count": page_count,
            "table_count": table_count,
            "non_empty_text_pages": non_empty_text_pages,
        },
        warnings=warnings,
    )
