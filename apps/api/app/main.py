from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.db.base import make_engine, session_factory
from app.services.ocr import build_ocr_service
from app.services.parsers.factory import build_document_parser
from app.services.storage import build_storage_adapter
from app.services.retrieval.runtime import build_search_retriever
from app.services.llm_runtime import build_llm_backend


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = getattr(app.state, "settings", None) or get_settings()
    engine = None

    # Per-process worker identity — set once at startup, used by the orphan
    # guard to avoid resetting in-flight runs owned by this process.
    worker_id = getattr(app.state, "worker_id", None) or uuid4()
    app.state.worker_id = worker_id

    app.state.settings = settings
    app.state.search_source_context_window = max(settings.search_source_context_window, 0)

    if settings.database_url:
        engine = make_engine(settings.database_url)
        session_factory.configure(bind=engine)
        app.state.db_engine = engine

        if settings.ingestion_recover_orphaned:
            from sqlalchemy.exc import OperationalError, ProgrammingError

            from app.repositories.ingestion import recover_orphaned_runs

            try:
                recovered = recover_orphaned_runs(
                    current_worker_id=worker_id,
                    stale_threshold_seconds=settings.ingestion_stale_threshold_seconds,
                )
                if recovered > 0:
                    import logging

                    logging.getLogger(__name__).info(
                        "Recovered %d orphaned ingestion run(s) on startup.", recovered
                    )
            except (OperationalError, ProgrammingError):
                # Only database-shape errors are tolerable here (e.g., fresh DB
                # before migrations). Anything else is a bug and must fail startup.
                import logging

                logging.getLogger(__name__).debug(
                    "Orphaned-run recovery skipped (table may not exist yet).", exc_info=True
                )

    storage = build_storage_adapter(settings)
    if storage is not None:
        app.state.document_storage = storage

    # Pre-injected storage (tests, embedders) counts as configured.
    effective_storage = storage if storage is not None else getattr(app.state, "document_storage", None)
    if (
        effective_storage is None
        and settings.workflow_backend == "in_process"
        and settings.parser_backend
        and settings.parser_backend.strip().lower() in {"docling", "docling-local"}
    ):
        raise RuntimeError(
            "parser_backend=docling requires a configured storage backend for "
            "in-process ingestion: set LOCAL_STORAGE_DIR (or the S3/SeaweedFS "
            "settings), or set PARSER_BACKEND='' to run the API without "
            "ingestion. Without storage, uploads return 503 and the parse "
            "stage cannot materialize source files."
        )

    if settings.parser_backend:
        from app.services.contextualizers.factory import build_chunk_contextualizer
        from app.workflows.dispatcher import InProcessDispatcher

        parser, parser_backend, parser_profile = build_document_parser(settings)
        # Keep a reference so we can close the parser's connection pool at shutdown.
        app.state.document_parser = parser

        if settings.workflow_backend == "temporal":
            from app.workflows.temporal_dispatcher import build_temporal_dispatcher

            app.state.dispatcher = build_temporal_dispatcher(settings)
        else:
            app.state.dispatcher = InProcessDispatcher(
                parser=parser,
                parser_backend=parser_backend,
                parser_profile=parser_profile,
                ocr_service=build_ocr_service(settings),
                storage=storage,
                contextualizer=build_chunk_contextualizer(settings),
                worker_id=worker_id,
            )

    search_retriever = build_search_retriever(settings=settings, state=app.state)
    if search_retriever is not None:
        app.state.search_retriever = search_retriever

    app.state.llm_backend = build_llm_backend(settings=settings, state=app.state)

    yield

    session_factory.configure(bind=None)

    if engine is not None:
        engine.dispose()

    if hasattr(app.state, "db_engine"):
        delattr(app.state, "db_engine")

    if hasattr(app.state, "document_storage"):
        delattr(app.state, "document_storage")

    if hasattr(app.state, "dispatcher"):
        dispatcher_close = getattr(app.state.dispatcher, "close", None)
        if dispatcher_close is not None:
            try:
                await dispatcher_close()
            except Exception:
                import logging

                logging.getLogger(__name__).debug(
                    "Dispatcher close failed at shutdown.", exc_info=True
                )
        delattr(app.state, "dispatcher")

    if hasattr(app.state, "settings"):
        delattr(app.state, "settings")

    if hasattr(app.state, "search_source_context_window"):
        delattr(app.state, "search_source_context_window")

    if hasattr(app.state, "search_retriever"):
        delattr(app.state, "search_retriever")

    # Close the remote parser's httpx connection pool if one was lazily created.
    if hasattr(app.state, "document_parser"):
        parser = app.state.document_parser
        if hasattr(parser, "close"):
            try:
                parser.close()
            except Exception:
                pass
        delattr(app.state, "document_parser")


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()

    # Fail fast: dev-auth must not be exposed on a non-loopback bind address.
    if active_settings.auth_mode == "dev":
        from app.core.security import assert_dev_auth_bind_is_loopback
        assert_dev_auth_bind_is_loopback(active_settings.server_host)

    app = FastAPI(
        title=active_settings.app_name,
        version=active_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
