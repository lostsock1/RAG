from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Uber-RAG API"
    app_version: str = "0.1.0"
    auth_mode: Literal["disabled", "dev", "oidc"] = "disabled"

    # OIDC verifier settings used by the runtime token verifier/JWKS path.
    oidc_issuer_url: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None

    # Deferred non-verifier OIDC settings retained for current claim-mapping/runtime compatibility.
    oidc_client_id: str | None = None
    oidc_username_claim: str = "preferred_username"
    oidc_groups_claim: str = "groups"
    oidc_roles_claim: str = "realm_access.roles"
    oidc_scopes_claim: str = "scope"
    database_url: str | None = None
    local_storage_dir: str | None = None
    storage_backend: Literal["local", "seaweedfs"] = "local"
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "uber-rag-documents"
    s3_region: str = "us-east-1"
    workflow_backend: Literal["in_process", "temporal"] = "in_process"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "uber-rag-ingestion"
    temporal_host_port: str | None = None
    parser_backend: str = "docling"
    parser_profile: str = "local-cpu"
    remote_parser_url: str | None = None
    remote_parser_api_key: str | None = None
    remote_parser_timeout_seconds: float = 30.0
    search_source_context_window: int = 1
    search_backend: Literal["disabled", "hybrid"] = "disabled"
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str | None = None
    qdrant_collection_name: str = "uber_rag_chunks"
    opensearch_host: str = "localhost"
    opensearch_port: int = 9200
    opensearch_username: str | None = None
    opensearch_password: str | None = None
    opensearch_use_ssl: bool = False
    opensearch_verify_certs: bool = True
    opensearch_index_name: str = "uber_rag_chunks"
    reranker_backend: Literal["disabled", "stub", "bge-reranker-v2-m3"] = "disabled"
    reranker_model_name: str = "BAAI/bge-reranker-v2-m3"
    reranker_batch_size: int = 8
    reranker_max_length: int = 512
    reranker_candidate_limit: int = 20
    context_builder_max_characters: int = Field(default=4000, ge=1)
    context_builder_max_blocks: int | None = Field(default=None, ge=1)
    llm_backend: Literal["disabled", "stub", "ppq"] = "disabled"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model_name: str = "meta-llama/Llama-3.3-70B-Instruct"
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_max_output_tokens: int = Field(default=512, ge=1)
    ocr_engine: str = "tesseract"
    postgres_user: str = "uber_rag"
    postgres_password: str = "uber_rag"
    postgres_db: str = "uber_rag"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin"
    minio_api_port: int = 9000
    minio_console_port: int = 9001
    keycloak_admin: str = "admin"
    keycloak_admin_password: str = "admin"
    keycloak_port: int = 8080

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
