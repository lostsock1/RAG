from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.repositories.ingestion import (
    list_ingestion_runs_for_context,
    write_ingestion_job_get_denied_audit_event,
    write_ingestion_job_get_audit_event,
    write_ingestion_job_retry_denied_audit_event,
    write_ingestion_job_retry_conflict_audit_event,
    write_ingestion_job_retry_audit_event,
    write_ingestion_run_list_audit_event,
)
from app.schemas.ingestion import (
    IngestionJobListResponse,
    IngestionJobResponse,
    IngestionRunListResponse,
    IngestionRunResponse,
)
from app.services.ingestion_service import get_ingestion_job, retry_ingestion_job

router = APIRouter()


def _build_ingestion_job_list_response(context: RequestContext) -> IngestionJobListResponse:
    runs = list_ingestion_runs_for_context(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        group_ids=context.group_ids,
    )
    write_ingestion_run_list_audit_event(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        run_ids=[run.id for run in runs],
    )
    return IngestionJobListResponse(items=[IngestionJobResponse.model_validate(run) for run in runs])


@router.get("/jobs", response_model=IngestionJobListResponse)
def list_ingestion_jobs_route(
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> IngestionJobListResponse:
    return _build_ingestion_job_list_response(context)


@router.get("/runs", response_model=IngestionRunListResponse, include_in_schema=False)
def list_ingestion_runs_route(
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> IngestionRunListResponse:
    response = _build_ingestion_job_list_response(context)
    return IngestionRunListResponse(items=[IngestionRunResponse.model_validate(run) for run in response.items])


@router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job_route(
    job_id: UUID,
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> IngestionJobResponse:
    run = get_ingestion_job(
        job_id=job_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        group_ids=context.group_ids,
    )
    if run is None:
        write_ingestion_job_get_denied_audit_event(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            job_id=job_id,
        )
        raise HTTPException(status_code=404, detail="Ingestion job not found")

    write_ingestion_job_get_audit_event(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        run=run,
    )

    return IngestionJobResponse.model_validate(run)


@router.post("/jobs/{job_id}/retry", response_model=IngestionJobResponse)
async def retry_ingestion_job_route(
    job_id: UUID,
    request: Request,
    context: RequestContext = Depends(require_scopes(["documents:write"])),
) -> IngestionJobResponse:
    existing_run = get_ingestion_job(
        job_id=job_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        group_ids=context.group_ids,
    )
    if existing_run is None:
        write_ingestion_job_retry_denied_audit_event(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            job_id=job_id,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found")

    previous_status = existing_run.status

    try:
        run = await retry_ingestion_job(
            request=request,
            job_id=job_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            group_ids=context.group_ids,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_409_CONFLICT:
            write_ingestion_job_retry_conflict_audit_event(
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                run=existing_run,
                current_status=previous_status,
            )
        raise

    if run is None:
        write_ingestion_job_retry_denied_audit_event(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            job_id=job_id,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found")

    write_ingestion_job_retry_audit_event(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        run=run,
        previous_status=previous_status,
    )

    return IngestionJobResponse.model_validate(run)
