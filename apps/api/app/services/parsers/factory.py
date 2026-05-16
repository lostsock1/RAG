from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.services.parsers.base import DocumentParser
from app.services.parsers.docling_backend import DoclingDocumentParser


def build_document_parser(settings: Settings) -> tuple[DocumentParser, str, str]:
    backend = settings.parser_backend.strip().lower()
    storage_root = Path(settings.local_storage_dir) if settings.local_storage_dir else None

    if backend in {"docling", "docling-local"}:
        return DoclingDocumentParser(storage_root=storage_root), "docling-local", "local-cpu"

    if backend == "remote":
        raise RuntimeError(
            "Parser backend 'remote' is not yet supported in runtime startup. Configure a local Docling backend for now."
        )

    raise RuntimeError(
        f"Unknown parser backend '{settings.parser_backend}'. Supported backends: docling, docling-local."
    )
