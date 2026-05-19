from fastapi import APIRouter

from app.api.routes.document_acl import router as document_acl_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.ingestion import router as ingestion_router
from app.api.routes.search import router as search_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/system", tags=["system"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])
api_router.include_router(document_acl_router, prefix="/documents", tags=["documents"])
api_router.include_router(ingestion_router, prefix="/ingestion", tags=["ingestion"])

api_router.include_router(search_router, prefix="/search", tags=["search"])
