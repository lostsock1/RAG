from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DenseVector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: list[float]
    dimension: int


class SparseVector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indices: list[int]
    values: list[float]


class EmbeddingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    dense: DenseVector
    sparse: SparseVector
