from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.core.request_context import RequestContext
from app.db.models.document import Document
from app.repositories.documents import (
    get_live_document_by_source_hash,
    get_or_create_document_by_source_hash,
    write_document_upload_audit_event,
)
from app.repositories.ingestion import create_ingestion_run
from app.schemas.documents import DocumentUploadForm
from app.services.storage import StorageAdapter

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class UploadPayload:
    file_name: str
    source: Path          # Path to a temp file containing the upload bytes
    source_hash: str      # Pre-computed SHA-256 hex digest (single-pass from route)
    content_length: int   # Byte count of the upload
    content_type: str
    form: DocumentUploadForm


@dataclass(slots=True)
class UploadResult:
    document: Document
    ingestion_run_id: UUID
    profile: str


def build_object_key(*, tenant_id: UUID, source_hash: str) -> str:
    return f"documents/{tenant_id}/{source_hash}"


def upload_document(
    *,
    context: RequestContext,
    payload: UploadPayload,
    storage: StorageAdapter,
    parser_backend: str,
    workflow_backend: str = "in_process",
) -> UploadResult:
    source_hash = payload.source_hash
    tenant_id = UUID(context.tenant_id)
    user_id = UUID(context.user_id)
    object_key = build_object_key(
        tenant_id=tenant_id,
        source_hash=source_hash,
    )
    existing_document = get_live_document_by_source_hash(
        tenant_id=tenant_id,
        owner_user_id=user_id,
        source_hash=source_hash,
    )

    if existing_document is not None:
        document = existing_document
        object_key = document.object_key or object_key
    else:
        with payload.source.open("rb") as fp:
            storage.put_object_stream(
                object_key=object_key,
                fp=fp,
                content_type=payload.content_type,
                content_length=payload.content_length,
            )

        try:
            document = get_or_create_document_by_source_hash(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                title=payload.form.title,
                source_type=payload.form.source_type,
                document_type=payload.form.document_type,
                language=payload.form.language,
                source_hash=source_hash,
                file_name=payload.file_name,
                file_size_bytes=payload.content_length,
                object_key=object_key,
            )
        except Exception:
            # DB write failed — best-effort delete the orphaned object so
            # storage does not accumulate bytes with no corresponding DB row.
            try:
                storage.delete_object(object_key=object_key)
            except Exception as cleanup_exc:
                _log.warning(
                    "Storage cleanup failed for object_key=%r after DB error: %s",
                    object_key,
                    cleanup_exc,
                )
            raise
        object_key = document.object_key or object_key

    run = create_ingestion_run(
        document_id=document.id,
        tenant_id=tenant_id,
        parser_backend=parser_backend,
        source_hash=source_hash,
        workflow_backend=workflow_backend,
        profile=payload.form.profile,
    )

    write_document_upload_audit_event(
        tenant_id=tenant_id,
        user_id=user_id,
        document_id=document.id,
        title=document.title,
        source_type=document.source_type,
        source_hash=source_hash,
        object_key=object_key,
        ingestion_status=document.ingestion_status,
        ingestion_run_id=run.id,
    )

    return UploadResult(document=document, ingestion_run_id=run.id, profile=run.profile)
