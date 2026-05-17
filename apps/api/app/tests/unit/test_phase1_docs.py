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
