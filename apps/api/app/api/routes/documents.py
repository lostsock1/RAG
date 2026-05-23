from __future__ import annotations

from hashlib import sha256
from tempfile import NamedTemporaryFile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from app.core.config import get_settings
from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.repositories.documents import list_documents_for_context, write_document_list_audit_event
from app.schemas.documents import DocumentResponse, DocumentUploadForm
from app.schemas.ingestion import DocumentUploadResponse
from app.services.document_service import UploadPayload, upload_document
from app.services.storage import get_storage_adapter

router = APIRouter()


@router.get("", response_model=dict[str, list[DocumentResponse]])
def list_documents_route(
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> dict[str, list[DocumentResponse]]:
    documents = list_documents_for_context(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        group_ids=context.group_ids,
    )
    write_document_list_audit_event(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        document_ids=[document.id for document in documents],
    )
    return {"items": [DocumentResponse.model_validate(document) for document in documents]}


@router.post("/upload", status_code=status.HTTP_201_CREATED, response_model=DocumentUploadResponse)
async def upload_document_route(
    request: Request,
    title: str = Form(...),
    source_type: str = Form(...),
    document_type: str | None = Form(default=None),
    language: str | None = Form(default=None),
    file: UploadFile = File(...),
    context: RequestContext = Depends(require_scopes(["documents:write"])),
) -> DocumentUploadResponse:
    settings = getattr(request.app.state, "settings", None) or get_settings()
    parser_backend = settings.parser_backend
    workflow_backend = settings.workflow_backend

    # Stream the upload to a temp file while computing SHA-256 in a single pass.
    # This avoids materialising the entire file in RAM.
    hasher = sha256()
    content_length = 0
    chunk_size = 256 * 1024  # 256 KB

    with NamedTemporaryFile(delete=False, suffix=".upload") as tmp:
        tmp_path = Path(tmp.name)
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
            content_length += len(chunk)
            tmp.write(chunk)

    source_hash = hasher.hexdigest()

    try:
        result = upload_document(
            context=context,
            payload=UploadPayload(
                file_name=file.filename or "upload.bin",
                source=tmp_path,
                source_hash=source_hash,
                content_length=content_length,
                content_type=file.content_type or "application/octet-stream",
                form=DocumentUploadForm(
                    title=title,
                    source_type=source_type,
                    document_type=document_type,
                    language=language,
                ),
            ),
            storage=get_storage_adapter(request),
            parser_backend=parser_backend,
            workflow_backend=workflow_backend,
        )
    finally:
        # Always clean up the temp file regardless of success or failure.
        if tmp_path.exists():
            tmp_path.unlink()

    dispatcher = getattr(request.app.state, "dispatcher", None)
    if dispatcher is not None:
        await dispatcher.dispatch(result.ingestion_run_id)

    return DocumentUploadResponse.model_validate(
        {**DocumentResponse.model_validate(result.document).model_dump(), "ingestion_run_id": result.ingestion_run_id}
    )
