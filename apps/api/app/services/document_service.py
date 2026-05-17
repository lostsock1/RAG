from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
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


@dataclass(slots=True)
class UploadPayload:
    file_name: str
    content: bytes
    content_type: str
    form: DocumentUploadForm


@dataclass(slots=True)
class UploadResult:
    document: Document
    ingestion_run_id: UUID


def build_object_key(*, tenant_id: str, source_hash: str) -> str:
    return f"documents/{tenant_id}/{source_hash}"


def upload_document(
    *,
    context: RequestContext,
    payload: UploadPayload,
    storage: StorageAdapter,
    parser_backend: str,
) -> UploadResult:
    source_hash = sha256(payload.content).hexdigest()
    tenant_id = UUID(context.tenant_id)
    user_id = UUID(context.user_id)
    object_key = build_object_key(
        tenant_id=context.tenant_id,
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
        storage.put_object(
            object_key=object_key,
            content=payload.content,
            content_type=payload.content_type,
        )

        document = get_or_create_document_by_source_hash(
            tenant_id=tenant_id,
            owner_user_id=user_id,
            title=payload.form.title,
            source_type=payload.form.source_type,
            document_type=payload.form.document_type,
            language=payload.form.language,
            source_hash=source_hash,
            file_name=payload.file_name,
            file_size_bytes=len(payload.content),
            object_key=object_key,
        )
        object_key = document.object_key or object_key

    run = create_ingestion_run(
        document_id=document.id,
        tenant_id=tenant_id,
        parser_backend=parser_backend,
        source_hash=source_hash,
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

    return UploadResult(document=document, ingestion_run_id=run.id)
