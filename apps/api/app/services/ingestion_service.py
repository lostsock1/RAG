from __future__ import annotations

from uuid import UUID

from app.repositories.ingestion import get_ingestion_run_for_context, store_parsed_artifact
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
