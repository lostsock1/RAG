from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from app.services.contextualizers.base import ChunkContextualizer

from app.services.ocr import OcrService
from app.services.parsers.base import DocumentParser
from app.services.storage import StorageAdapter
from app.services.embedders.base import Embedder
from app.services.indexers.base import VectorIndexer, LexicalIndexer
from app.workflows.pipeline_runner import PipelineRunner

logger = logging.getLogger(__name__)


class WorkflowDispatcher(Protocol):
    async def dispatch(self, run_id: UUID) -> None: ...


class InProcessDispatcher:
    """In-process dispatcher that runs the ingestion pipeline via asyncio.create_task.

    Delegates actual pipeline execution to PipelineRunner so the same business
    logic is shared between in-process and Temporal orchestration backends.
    """

    def __init__(
        self,
        parser: DocumentParser,
        parser_backend: str,
        parser_profile: str,
        ocr_service: OcrService | None = None,
        storage: StorageAdapter | None = None,
        runner: PipelineRunner | None = None,
        embedder: Embedder | None = None,
        vector_indexer: VectorIndexer | None = None,
        lexical_indexer: LexicalIndexer | None = None,
        contextualizer: "ChunkContextualizer | None" = None,
        worker_id: UUID | None = None,
    ) -> None:
        self._runner = runner or PipelineRunner(
            parser=parser,
            parser_backend=parser_backend,
            parser_profile=parser_profile,
            ocr_service=ocr_service,
            storage=storage,
            embedder=embedder,
            vector_indexer=vector_indexer,
            lexical_indexer=lexical_indexer,
            contextualizer=contextualizer,
            worker_id=worker_id,
        )
        # Retain direct attribute access for existing tests that inspect internals
        self._parser = parser
        self._parser_backend = parser_backend
        self._parser_profile = parser_profile
        self._ocr_service = ocr_service
        self._storage = storage

    async def dispatch(self, run_id: UUID) -> None:
        loop = asyncio.get_event_loop()
        loop.create_task(self._run_pipeline(run_id))

    async def _run_pipeline(self, run_id: UUID) -> None:
        try:
            await asyncio.to_thread(self._execute_pipeline, run_id)
        except Exception:
            logger.exception("Ingestion pipeline failed unexpectedly for run %s", run_id)

    def _execute_pipeline(self, run_id: UUID) -> None:
        self._runner.run(run_id)
