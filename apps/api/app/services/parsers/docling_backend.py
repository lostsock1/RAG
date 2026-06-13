from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID

from app.schemas.parsed_artifacts import (
    ParsedArtifact,
    ParsedBlock,
    ParsedPage,
    ParsedTable,
    ParserProvenance,
)
from app.services.parsers.base import DocumentParser, ParseRequest


class DoclingDocumentParser(DocumentParser):
    backend_name = "docling-local"

    def __init__(
        self,
        converter: Callable[[ParseRequest], ParsedArtifact] | None = None,
        storage_root: Path | None = None,
    ) -> None:
        self._converter = converter
        self._storage_root = storage_root
        # Cached DocumentConverter instance — created once on first parse() call.
        # DocumentConverter loads multi-hundred-MB models; re-creating it per call
        # pays the full cold-start cost every time.
        # NOTE: this instance is NOT thread-safe across processes; keep the
        # existing one-per-FastAPI-process pattern.
        self._document_converter: Any | None = None

    def parse(self, request: ParseRequest) -> ParsedArtifact:
        parser_backend = request.parser_backend or self.backend_name

        if self._converter is not None:
            artifact = self._converter(request)
            artifact.provenance.parser_backend = parser_backend
            artifact.provenance.profile = request.profile
            return artifact

        # Resolve source path: prefer materialized local path, fall back to storage_root + object_key
        source_path = Path(request.local_source_path) if request.local_source_path else None
        if source_path is None:
            if self._storage_root is None:
                raise RuntimeError(
                    "Docling parsing requires either a materialized local source path "
                    "or a configured local storage root when no converter is injected. "
                    "Configure a storage root or pass local_source_path before running local Docling parsing."
                )
            source_path = self._storage_root / request.object_key

        if not source_path.is_file():
            raise RuntimeError(
                f"Docling source file not found for object_key '{request.object_key}' at '{source_path}'."
            )

        try:
            document_converter_module = import_module("docling.document_converter")
        except ImportError as exc:
            raise RuntimeError(
                "Docling parsing requires the docling package. Install the docling package or inject a converter before running Phase 2 parsing."
            ) from exc

        try:
            # Lazy-init: create DocumentConverter once and reuse across calls.
            # This avoids paying the multi-second cold-start cost on every parse.
            if self._document_converter is None:
                self._document_converter = document_converter_module.DocumentConverter()
            conversion_result = self._document_converter.convert(source_path)
            return _normalize_docling_result(
                request=request,
                conversion_result=conversion_result,
                parser_backend=parser_backend,
                parser_version=_resolve_docling_version(),
            )
        except Exception as exc:
            raise RuntimeError(
                f"Docling conversion failed for object_key '{request.object_key}': {exc}"
            ) from exc


# DoclingDocument item labels (DocItemLabel values), compared as strings so the
# adapter does not import the enum at module load. Verified against docling-core
# 2.82: headings carry `section_header`/`title`; `SectionHeaderItem.level` is the
# 1-based heading depth (title is the level-0 root).
_HEADING_LABELS = frozenset({"title", "section_header"})
# Labels excluded from a page's prose `text` (the loose chunker splits page.text
# into paragraphs and reads tables separately, so tables/figures must not also
# land in the prose stream and double-count).
_NON_PROSE_LABELS = frozenset({"table", "picture", "chart"})
# Furniture safety net. `iterate_items()` walks the BODY content layer by default
# and already excludes running heads/footers, but guard explicitly.
_FURNITURE_LABELS = frozenset({"page_header", "page_footer"})


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
        pages=_extract_pages_and_blocks(document),
        tables=_normalize_tables(document),
        provenance=ParserProvenance(
            parser_backend=parser_backend,
            parser_version=parser_version,
            profile=request.profile,
        ),
    )


def _extract_pages_and_blocks(document: Any) -> list[ParsedPage]:
    """Walk the DoclingDocument body tree in reading order.

    Produces, per page: prose `text` (loose-profile contract — text-like items
    only, tables/figures excluded) and rich `blocks` carrying block type, page
    anchor, bbox, heading level, and the section-header breadcrumb (book-profile
    contract). The heading breadcrumb is tracked with a stack keyed on
    `SectionHeaderItem.level`; the document title is the level-0 root.
    """
    pages: dict[int, dict[str, list]] = {}
    heading_stack: list[tuple[int, str]] = []
    current_page = 1

    for item, _tree_level in document.iterate_items():
        label = _label_of(item)
        if label is None or label in _FURNITURE_LABELS:
            continue

        text = (getattr(item, "text", None) or "").strip()
        if label == "table":
            # TableItems carry no `.text`; surface the markdown so the book
            # chunker can emit atomic table leaves. Tables are in _NON_PROSE_LABELS
            # so this never pollutes a page's prose `text`.
            text = _table_markdown(item, document).strip()
        page_no, bbox = _first_prov(item)
        if page_no is not None:
            current_page = page_no
        page_no = page_no or current_page

        # Maintain the heading breadcrumb.
        block_level: int | None = None
        if label == "title":
            block_level = 0
            heading_stack = [(0, text)] if text else []
        elif label == "section_header":
            block_level = int(getattr(item, "level", 1) or 1)
            heading_stack = [(lvl, t) for (lvl, t) in heading_stack if lvl < block_level]
            if text:
                heading_stack.append((block_level, text))

        heading_path = [t for (_lvl, t) in heading_stack]

        block = ParsedBlock(
            block_type=label,
            text=text or None,
            bbox=bbox,
            level=block_level,
            heading_path=heading_path,
        )
        bucket = pages.setdefault(page_no, {"texts": [], "blocks": []})
        bucket["blocks"].append(block)
        if text and label not in _NON_PROSE_LABELS:
            bucket["texts"].append(text)

    return [
        ParsedPage(
            page_number=page_no,
            text="\n\n".join(pages[page_no]["texts"]),
            blocks=pages[page_no]["blocks"],
        )
        for page_no in sorted(pages)
    ]


def _normalize_tables(document: Any) -> list[ParsedTable]:
    normalized_tables: list[ParsedTable] = []
    for table in _iter_items(getattr(document, "tables", [])):
        normalized_tables.append(
            ParsedTable(
                page_number=_resolve_table_page_number(table),
                bbox=_resolve_table_bbox(table),
                markdown=_table_markdown(table, document),
            )
        )

    normalized_tables.sort(key=lambda table: table.page_number)
    return normalized_tables


def _resolve_docling_version() -> str:
    try:
        return package_version("docling")
    except PackageNotFoundError:
        return "unknown"


def _label_of(item: Any) -> str | None:
    label = getattr(item, "label", None)
    return getattr(label, "value", label) if label is not None else None


def _first_prov(item: Any) -> tuple[int | None, list[float] | None]:
    prov_items = getattr(item, "prov", None)
    if not prov_items:
        return None, None
    first = prov_items[0]
    raw_page = getattr(first, "page_no", None)
    page_no = int(raw_page) if raw_page is not None else None
    bbox = None
    box = getattr(first, "bbox", None)
    if box is not None and all(hasattr(box, attr) for attr in ("l", "t", "r", "b")):
        bbox = [float(box.l), float(box.t), float(box.r), float(box.b)]
    return page_no, bbox


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


def _table_markdown(table: Any, document: Any) -> str:
    # docling-core 2.x: TableItem.export_to_markdown(doc) takes the owning
    # document; the no-arg form is deprecated and loses cell content. Fall back
    # to the no-arg call (older docling / injected fakes) then a plain attribute.
    exporter = getattr(table, "export_to_markdown", None)
    if callable(exporter):
        try:
            return str(exporter(document))
        except TypeError:
            return str(exporter())

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
