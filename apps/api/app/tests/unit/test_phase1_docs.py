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
    assert "persistence/status scaffolding" in api_contract
    assert "DocumentUploadResponse" in openapi_text
    assert "ingestion_run_id:" in openapi_text
