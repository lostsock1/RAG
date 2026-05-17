from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.services.parsers.base import DocumentParser
from app.services.parsers.docling_backend import DoclingDocumentParser
from app.services.parsers.remote_backend import RemoteDocumentParser


def build_document_parser(
    settings: Settings,
    remote_parser: RemoteDocumentParser | None = None,
) -> tuple[DocumentParser, str, str]:
    backend = settings.parser_backend.strip().lower()
    profile = settings.parser_profile.strip().lower()
    storage_root = Path(settings.local_storage_dir) if settings.local_storage_dir else None

    if profile not in {"local-cpu", "local-gpu", "remote-api"}:
        raise RuntimeError(
            f"Unknown parser profile '{settings.parser_profile}'. Supported profiles: local-cpu, local-gpu, remote-api."
        )

    if backend in {"docling", "docling-local"}:
        if profile == "remote-api":
            raise RuntimeError(
                "Parser backend 'docling' cannot run with parser_profile 'remote-api'. Use a remote parser adapter for remote-api deployments."
            )
        return DoclingDocumentParser(storage_root=storage_root), "docling-local", profile

    if backend in {"remote", "remote-api"}:
        if profile != "remote-api":
            raise RuntimeError(
                f"Parser backend '{settings.parser_backend}' requires parser_profile 'remote-api', got '{settings.parser_profile}'."
            )
        if remote_parser is None:
            raise RuntimeError(
                "Parser backend 'remote' requires an injected remote parser adapter when parser_profile='remote-api'."
            )
        return remote_parser, "remote-api", "remote-api"

    raise RuntimeError(
        f"Unknown parser backend '{settings.parser_backend}'. Supported backends: docling, docling-local, remote."
    )
