from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.db.base import make_engine, session_factory
from app.services.storage import build_storage_adapter


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = getattr(app.state, "settings", None) or get_settings()
    engine = None

    app.state.settings = settings

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
        from app.services.parsers.docling_backend import DoclingDocumentParser
        from app.workflows.dispatcher import InProcessDispatcher

        parser = DoclingDocumentParser()
        app.state.dispatcher = InProcessDispatcher(parser=parser)

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
