from pathlib import Path


def test_phase1_gate_checklist_exists() -> None:
    path = Path("docs/uber-rag/PHASE1_GATE_CHECKLIST.md")
    assert path.exists()
    text = path.read_text()
    assert "Gate A" in text
    assert "Gate B" in text
    assert "Gate C" in text
    assert "Gate D" in text


def test_phase1_contract_subset_is_documented() -> None:
    text = Path("docs/uber-rag/API_CONTRACT.md").read_text()
    assert "## Phase 1 frozen subset" in text
    assert "/api/v1/system/health" in text
    assert "/api/v1/documents/upload" in text
    assert "/api/v1/documents" in text
    assert "/api/v1/documents/{document_id}/acl" in text


def test_phase2_foundation_contract_documents_upload_response_and_ingestion_scaffold_are_documented() -> None:
    api_contract = Path("docs/uber-rag/API_CONTRACT.md").read_text()
    openapi_text = Path("docs/uber-rag/api/openapi.yaml").read_text()

    assert "ingestion_run_id" in api_contract
    assert "persistence/status scaffolding" in api_contract or "persistence/status scaffold endpoints" in api_contract
    assert "DocumentUploadResponse" in openapi_text
    assert "ingestion_run_id:" in openapi_text


def test_ingestion_openapi_documents_retry_route_and_dispatch_truthfully() -> None:
    openapi_text = Path("docs/uber-rag/api/openapi.yaml").read_text()
    retry_block = openapi_text.split('/ingestion/jobs/{job_id}/retry:')[1].split('/ingestion/jobs/{job_id}/cancel:')[0]

    assert "/ingestion/jobs/{job_id}/retry:" in openapi_text
    assert "operationId: retryIngestionJob" in openapi_text
    assert "workflow-backend-neutral dispatcher seam" in openapi_text
    assert "until real workflow dispatch is implemented" not in openapi_text
    assert '"404":' in retry_block
    assert '"409":' in retry_block
    assert 'detail:' in retry_block
    assert 'not found or denied' in retry_block
    assert '$ref: "#/components/schemas/Error"' not in retry_block


def test_search_openapi_and_contract_match_thin_search_slice() -> None:
    api_contract = Path('docs/uber-rag/API_CONTRACT.md').read_text()
    openapi_text = Path('docs/uber-rag/api/openapi.yaml').read_text()

    assert 'Current thin /search slice' in api_contract
    assert 'Search retrieval is not configured yet. Configure a search retriever before using /search.' in api_contract
    assert 'top_k:' in openapi_text
    assert 'document_title:' in openapi_text
    assert 'citation_id:' in openapi_text
    assert 'source_viewer_url:' in openapi_text
    assert 'route:' in openapi_text
    assert 'items:' in openapi_text
    assert 'total:' in openapi_text
    assert '"503":' in openapi_text
    assert '/search/sources/{chunk_id}:' in openapi_text
    assert 'SearchSourceResponse' in openapi_text
    assert 'collections:' not in openapi_text.split('    SearchRequest:')[1].split('    SearchResponse:')[0]
    search_response_block = openapi_text.split('    SearchResponse:')[1].split('    # ── Chat')[0]
    assert 'results:' not in search_response_block
    assert 'total_hits:' not in search_response_block
    assert 'retrieval_mode_used:' not in search_response_block


def test_acl_bootstrap_policy_api_and_public_visibility_are_documented() -> None:
    api_contract = Path('docs/uber-rag/API_CONTRACT.md').read_text()
    security_acl = Path('docs/uber-rag/SECURITY_ACL.md').read_text()
    openapi_text = Path('docs/uber-rag/api/openapi.yaml').read_text()

    assert '/api/v1/acl/bootstrap-policy' in api_contract
    assert '/acl/bootstrap-policy:' in openapi_text
    assert 'tenant-scoped to authenticated users in the same tenant' in security_acl


def test_phase3_entry_note_exists_and_mentions_fusion_choice() -> None:
    text = Path('docs/uber-rag/research/2026-05-20-phase-3-entry.md').read_text()

    assert 'Qdrant' in text
    assert 'OpenSearch' in text
    assert 'BGE-M3' in text
    assert 'RRF' in text or 'DBSF' in text
