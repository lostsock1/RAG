from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Request, status

from app.repositories.ingestion import (
    get_ingestion_run_for_context,
    prepare_ingestion_run_for_retry,
    store_parsed_artifact,
)
from app.schemas.parsed_artifacts import ParsedArtifact


def get_ingestion_job(*, job_id: UUID, tenant_id: str, user_id: str, group_ids: list[str]):
    return get_ingestion_run_for_context(
        job_id=job_id,
        tenant_id=tenant_id,
        user_id=user_id,
        group_ids=group_ids,
    )


def persist_parse_result(*, run_id: UUID, artifact: ParsedArtifact):
    return store_parsed_artifact(run_id=run_id, artifact=artifact)


async def retry_ingestion_job(*, request: Request, job_id: UUID, tenant_id: str, user_id: str, group_ids: list[str]):
    run = get_ingestion_run_for_context(
        job_id=job_id,
        tenant_id=tenant_id,
        user_id=user_id,
        group_ids=group_ids,
    )
    if run is None:
        return None

    try:
        retried_run = prepare_ingestion_run_for_retry(run_id=job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    dispatcher = getattr(request.app.state, "dispatcher", None)
    if dispatcher is not None:
        await dispatcher.dispatch(job_id)
        refreshed_run = get_ingestion_run_for_context(
            job_id=job_id,
            tenant_id=tenant_id,
            user_id=user_id,
            group_ids=group_ids,
        )
        return refreshed_run or retried_run

    return retried_run
