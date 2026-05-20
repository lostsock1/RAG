from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.db.base import make_engine, session_factory
from app.services.ocr import build_ocr_service
from app.services.parsers.factory import build_document_parser
from app.services.storage import build_storage_adapter
from app.services.retrieval.runtime import build_search_retriever


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = getattr(app.state, "settings", None) or get_settings()
    engine = None

    app.state.settings = settings
    app.state.search_source_context_window = max(settings.search_source_context_window, 0)

    if settings.database_url:
        engine = make_engine(settings.database_url)
        session_factory.configure(bind=engine)
        app.state.db_engine = engine

        from app.repositories.ingestion import recover_orphaned_runs

        try:
            recovered = recover_orphaned_runs()
            if recovered > 0:
                import logging

                logging.getLogger(__name__).info(
                    "Recovered %d orphaned ingestion run(s) on startup.", recovered
                )
        except Exception:
            import logging

            logging.getLogger(__name__).debug(
                "Orphaned-run recovery skipped (table may not exist yet).", exc_info=True
            )

    storage = build_storage_adapter(settings)
    if storage is not None:
        app.state.document_storage = storage

    if settings.parser_backend:
        from app.workflows.dispatcher import InProcessDispatcher

        parser, parser_backend, parser_profile = build_document_parser(settings)

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
            )

    search_retriever = build_search_retriever(settings=settings, state=app.state)
    if search_retriever is not None:
        app.state.search_retriever = search_retriever

    yield

    session_factory.configure(bind=None)

    if engine is not None:
        engine.dispose()

    if hasattr(app.state, "db_engine"):
        delattr(app.state, "db_engine")

    if hasattr(app.state, "document_storage"):
        delattr(app.state, "document_storage")

    if hasattr(app.state, "dispatcher"):
        delattr(app.state, "dispatcher")

    if hasattr(app.state, "settings"):
        delattr(app.state, "settings")

    if hasattr(app.state, "search_source_context_window"):
        delattr(app.state, "search_source_context_window")

    if hasattr(app.state, "search_retriever"):
        delattr(app.state, "search_retriever")


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    app = FastAPI(
        title=active_settings.app_name,
        version=active_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
