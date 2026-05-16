from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID

from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance
from app.services.parsers.base import DocumentParser, ParseRequest


class DoclingDocumentParser(DocumentParser):
    backend_name = "docling"

    def __init__(
        self,
        converter: Callable[[ParseRequest], ParsedArtifact] | None = None,
        storage_root: Path | None = None,
    ) -> None:
        self._converter = converter
        self._storage_root = storage_root

    def parse(self, request: ParseRequest) -> ParsedArtifact:
        if self._converter is not None:
            artifact = self._converter(request)
            artifact.provenance.parser_backend = self.backend_name
            artifact.provenance.profile = request.profile
            return artifact

        if self._storage_root is None:
            raise RuntimeError(
                "Docling parsing requires a local storage root when no converter is injected. Configure a storage root before running local Docling parsing."
            )

        source_path = self._storage_root / request.object_key
        if not source_path.is_file():
            raise RuntimeError(
                f"Docling source file not found for object_key '{request.object_key}' under storage root '{self._storage_root}'."
            )

        try:
            document_converter_module = import_module("docling.document_converter")
        except ImportError as exc:
            raise RuntimeError(
                "Docling parsing requires the docling package. Install the docling package or inject a converter before running Phase 2 parsing."
            ) from exc

        try:
            converter = document_converter_module.DocumentConverter()
            conversion_result = converter.convert(source_path)
            return _normalize_docling_result(
                request=request,
                conversion_result=conversion_result,
                parser_backend=self.backend_name,
                parser_version=_resolve_docling_version(),
            )
        except Exception as exc:
            raise RuntimeError(
                f"Docling conversion failed for object_key '{request.object_key}'."
            ) from exc


def _normalize_docling_result(
    *,
    request: ParseRequest,
    conversion_result: Any,
    parser_backend: str,
    parser_version: str,
) -> ParsedArtifact:
    document = conversion_result.document

    return ParsedArtifact(
        document_id=UUID(request.document_id),
        pages=_normalize_pages(document.pages),
        tables=_normalize_tables(getattr(document, "tables", [])),
        provenance=ParserProvenance(
            parser_backend=parser_backend,
            parser_version=parser_version,
            profile=request.profile,
        ),
    )


def _normalize_pages(raw_pages: Any) -> list[ParsedPage]:
    if isinstance(raw_pages, dict):
        page_items = sorted(raw_pages.items())
        return [
            ParsedPage(
                page_number=_resolve_page_number(page, fallback=page_number),
                text=_page_text(page),
                blocks=[],
            )
            for page_number, page in page_items
        ]

    normalized_pages: list[ParsedPage] = []
    for index, page in enumerate(_iter_items(raw_pages), start=1):
        normalized_pages.append(
            ParsedPage(
                page_number=_resolve_page_number(page, fallback=index),
                text=_page_text(page),
                blocks=[],
            )
        )

    normalized_pages.sort(key=lambda page: page.page_number)
    return normalized_pages


def _normalize_tables(raw_tables: Any) -> list[ParsedTable]:
    normalized_tables: list[ParsedTable] = []
    for table in _iter_items(raw_tables):
        normalized_tables.append(
            ParsedTable(
                page_number=_resolve_table_page_number(table),
                bbox=_resolve_table_bbox(table),
                markdown=_table_markdown(table),
            )
        )

    normalized_tables.sort(key=lambda table: table.page_number)
    return normalized_tables


def _resolve_docling_version() -> str:
    try:
        return package_version("docling")
    except PackageNotFoundError:
        return "unknown"


def _resolve_page_number(page: Any, *, fallback: int) -> int:
    return int(
        getattr(page, "page_number", None)
        or getattr(page, "page_no", None)
        or fallback
    )


def _page_text(page: Any) -> str:
    if hasattr(page, "export_to_markdown"):
        return str(page.export_to_markdown())

    text = getattr(page, "text", None)
    if text is not None:
        return str(text)

    return ""


def _resolve_table_page_number(table: Any) -> int:
    explicit_page_number = getattr(table, "page_number", None) or getattr(table, "page_no", None)
    if explicit_page_number is not None:
        return int(explicit_page_number)

    provenance_items = list(_iter_items(getattr(table, "prov", [])))
    if provenance_items:
        return int(getattr(provenance_items[0], "page_no", 1))

    return 1


def _resolve_table_bbox(table: Any) -> list[float]:
    provenance_items = list(_iter_items(getattr(table, "prov", [])))
    if provenance_items:
        bbox = getattr(provenance_items[0], "bbox", None)
        if bbox is not None:
            if all(hasattr(bbox, attr) for attr in ("l", "t", "r", "b")):
                return [float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b)]

            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                return [float(value) for value in bbox]

    fallback_bbox = getattr(table, "bbox", None)
    if isinstance(fallback_bbox, (list, tuple)) and len(fallback_bbox) == 4:
        return [float(value) for value in fallback_bbox]

    return [0.0, 0.0, 0.0, 0.0]


def _table_markdown(table: Any) -> str:
    if hasattr(table, "export_to_markdown"):
        return str(table.export_to_markdown())

    markdown = getattr(table, "markdown", None)
    if markdown is not None:
        return str(markdown)

    return ""


def _iter_items(value: Any) -> Iterable[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return value
    return value
