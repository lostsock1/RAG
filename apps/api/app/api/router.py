from fastapi import APIRouter

from app.api.routes.answers_verify import router as answers_verify_router
from app.api.routes.citations import router as citations_router
from app.api.routes.acl_policy import router as acl_policy_router
from app.api.routes.chat import router as chat_router
from app.api.routes.document_acl import router as document_acl_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.ingestion import router as ingestion_router
from app.api.routes.search import router as search_router
from app.api.routes.search_sources import router as search_sources_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/system", tags=["system"])
api_router.include_router(acl_policy_router, prefix="/acl", tags=["acl"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])
api_router.include_router(document_acl_router, prefix="/documents", tags=["documents"])
api_router.include_router(ingestion_router, prefix="/ingestion", tags=["ingestion"])

api_router.include_router(search_router, prefix="/search", tags=["search"])
api_router.include_router(search_sources_router, prefix="/search", tags=["search"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(citations_router, prefix="/citations", tags=["citations"])
api_router.include_router(answers_verify_router, prefix="/answers", tags=["answers"])
