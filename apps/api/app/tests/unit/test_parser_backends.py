from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from typing import cast
from uuid import UUID

import httpx
import pytest

import app.services.parsers.docling_backend as docling_backend
from app.core.config import Settings
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance
from app.services.ocr import build_ocr_service
from app.services.parsers.base import ParseRequest
from app.services.parsers.docling_backend import DoclingDocumentParser
from app.services.parsers.factory import build_document_parser
from app.services.parsers.remote_backend import RemoteDocumentParser


CanonicalProfile = Literal["local-cpu", "local-gpu", "remote-api"]


def _build_artifact(*, profile: CanonicalProfile = "local-cpu") -> ParsedArtifact:
    return ParsedArtifact(
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        pages=[ParsedPage(page_number=1, text="Example", blocks=[])],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 1, 1], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="docling-local", parser_version="1.0", profile=profile),
    )


def test_remote_document_parser_overrides_profile_from_request() -> None:
    parser = RemoteDocumentParser(invoke_remote_parser=lambda request: _build_artifact())

    artifact = parser.parse(
        ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/sample.txt",
            content_type="text/plain",
            profile="remote-api",
            parser_backend="remote-api",
        )
    )

    assert artifact.provenance.parser_backend == "remote-api"
    assert artifact.provenance.profile == "remote-api"


def test_remote_document_parser_calls_http_transport_and_normalizes_provenance() -> None:
    recorded: dict[str, object] = {}

    class TransportStub:
        def post(self, url: str, *, json: dict, headers: dict[str, str], timeout: float):
            recorded["url"] = url
            recorded["json"] = json
            recorded["headers"] = headers
            recorded["timeout"] = timeout
            return httpx.Response(
                200,
                json={
                    "document_id": "11111111-1111-1111-1111-111111111111",
                    "pages": [{"page_number": 1, "text": "Remote page", "blocks": []}],
                    "tables": [],
                    "provenance": {
                        "parser_backend": "docling-local",
                        "parser_version": "2026.05",
                        "profile": "local-cpu",
                    },
                },
            )

    parser = RemoteDocumentParser(
        endpoint_url="https://parser.internal/parse",
        transport=TransportStub(),
        api_key="secret-token",
        timeout_seconds=12.5,
    )

    artifact = parser.parse(
        ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/sample.pdf",
            content_type="application/pdf",
            profile="remote-api",
            parser_backend="remote-api",
            local_source_path="/tmp/materialized/sample.pdf",
        )
    )

    assert recorded["url"] == "https://parser.internal/parse"
    assert recorded["headers"] == {"Authorization": "Bearer secret-token"}
    assert recorded["timeout"] == 12.5
    assert recorded["json"] == {
        "document_id": "11111111-1111-1111-1111-111111111111",
        "object_key": "documents/sample.pdf",
        "content_type": "application/pdf",
        "profile": "remote-api",
        "parser_backend": "remote-api",
        "local_source_path": "/tmp/materialized/sample.pdf",
    }
    assert artifact.pages[0].text == "Remote page"
    assert artifact.provenance.parser_backend == "remote-api"
    assert artifact.provenance.profile == "remote-api"
    assert artifact.provenance.parser_version == "2026.05"


def test_remote_document_parser_raises_clear_error_when_remote_service_fails() -> None:
    request = httpx.Request("POST", "https://parser.internal/parse")
    response = httpx.Response(502, request=request, text="upstream parser unavailable")

    class TransportStub:
        def post(self, url: str, *, json: dict, headers: dict[str, str], timeout: float):
            return response

    parser = RemoteDocumentParser(
        endpoint_url="https://parser.internal/parse",
        transport=TransportStub(),
    )

    with pytest.raises(RuntimeError) as exc_info:
        parser.parse(
            ParseRequest(
                document_id="11111111-1111-1111-1111-111111111111",
                object_key="documents/sample.pdf",
                content_type="application/pdf",
                profile="remote-api",
                parser_backend="remote-api",
            )
        )

    message = str(exc_info.value)
    assert "remote document parsing failed" in message.lower()
    assert "502" in message
    assert "upstream parser unavailable" in message


def test_docling_document_parser_uses_request_backend_for_injected_converter() -> None:
    parser = DoclingDocumentParser(
        converter=lambda request: _build_artifact(profile=cast(CanonicalProfile, request.profile))
    )

    artifact = parser.parse(
        ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/sample.pdf",
            content_type="application/pdf",
            profile="local-gpu",
            parser_backend="docling-local",
        )
    )

    assert artifact.provenance.parser_backend == "docling-local"
    assert artifact.provenance.profile == "local-gpu"


def test_build_document_parser_maps_docling_to_local_docling_runtime(tmp_path: Path) -> None:
    parser, backend, profile = build_document_parser(
        Settings(parser_backend="docling", local_storage_dir=str(tmp_path))
    )

    assert isinstance(parser, DoclingDocumentParser)
    assert parser._storage_root == tmp_path
    assert backend == "docling-local"
    assert profile == "local-cpu"


def test_build_document_parser_maps_docling_local_to_local_docling_runtime(tmp_path: Path) -> None:
    parser, backend, profile = build_document_parser(
        Settings(parser_backend="docling-local", local_storage_dir=str(tmp_path))
    )

    assert isinstance(parser, DoclingDocumentParser)
    assert parser._storage_root == tmp_path
    assert backend == "docling-local"
    assert profile == "local-cpu"


def test_build_document_parser_supports_local_gpu_profile_with_local_docling_runtime(tmp_path: Path) -> None:
    parser, backend, profile = build_document_parser(
        Settings(
            parser_backend="docling",
            parser_profile="local-gpu",
            local_storage_dir=str(tmp_path),
        )
    )

    assert isinstance(parser, DoclingDocumentParser)
    assert parser._storage_root == tmp_path
    assert backend == "docling-local"
    assert profile == "local-gpu"


def test_build_document_parser_allows_docling_with_seaweedfs_storage(tmp_path: Path) -> None:
    parser, backend, profile = build_document_parser(
        Settings(
            parser_backend="docling",
            storage_backend="seaweedfs",
            local_storage_dir=str(tmp_path),
        )
    )

    assert isinstance(parser, DoclingDocumentParser)
    assert backend == "docling-local"
    assert profile == "local-cpu"


def test_build_document_parser_supports_remote_api_profile_with_injected_adapter() -> None:
    remote_parser = RemoteDocumentParser(invoke_remote_parser=lambda request: _build_artifact())

    parser, backend, profile = build_document_parser(
        Settings(parser_backend="remote", parser_profile="remote-api"),
        remote_parser=remote_parser,
    )

    assert parser is remote_parser
    assert backend == "remote-api"
    assert profile == "remote-api"


def test_build_document_parser_builds_real_remote_parser_from_settings() -> None:
    class TransportStub:
        def post(self, url: str, *, json: dict, headers: dict[str, str], timeout: float):
            return httpx.Response(
                200,
                json={
                    "document_id": json["document_id"],
                    "pages": [{"page_number": 1, "text": "built from settings", "blocks": []}],
                    "tables": [],
                    "provenance": {
                        "parser_backend": "remote-api",
                        "parser_version": "1.2.3",
                        "profile": "remote-api",
                    },
                },
            )

    parser, backend, profile = build_document_parser(
        Settings(
            parser_backend="remote",
            parser_profile="remote-api",
            remote_parser_url="https://parser.internal/parse",
            remote_parser_api_key="secret-token",
            remote_parser_timeout_seconds=9.0,
        ),
        remote_transport=TransportStub(),
    )

    artifact = parser.parse(
        ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/sample.pdf",
            content_type="application/pdf",
            profile="remote-api",
            parser_backend="remote-api",
        )
    )

    assert isinstance(parser, RemoteDocumentParser)
    assert backend == "remote-api"
    assert profile == "remote-api"
    assert artifact.pages[0].text == "built from settings"


def test_build_ocr_service_uses_remote_truthful_defaults_for_remote_api_profile() -> None:
    service = build_ocr_service(Settings(parser_backend="remote", parser_profile="remote-api"))

    assert service.inspect(
        request=ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/sample.txt",
            content_type="text/plain",
            profile="remote-api",
            parser_backend="remote-api",
        ),
        artifact=_build_artifact(profile="remote-api"),
    ).provider == "remote-api"


def test_build_document_parser_rejects_remote_backend_without_injected_adapter() -> None:
    with pytest.raises(RuntimeError) as exc_info:
        build_document_parser(Settings(parser_backend="remote", parser_profile="remote-api"))

    assert "remote parser adapter" in str(exc_info.value).lower()
    assert "remote-api" in str(exc_info.value)


def test_build_document_parser_rejects_remote_backend_without_remote_parser_url() -> None:
    with pytest.raises(RuntimeError) as exc_info:
        build_document_parser(
            Settings(
                parser_backend="remote",
                parser_profile="remote-api",
                remote_parser_url=None,
            )
        )

    message = str(exc_info.value)
    assert "remote_parser_url" in message
    assert "remote-api" in message


def test_build_document_parser_rejects_unknown_profile(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError) as exc_info:
        build_document_parser(
            Settings(
                parser_backend="docling",
                parser_profile="moon-cluster",
                local_storage_dir=str(tmp_path),
            )
        )

    assert "Unknown parser profile" in str(exc_info.value)
    assert "moon-cluster" in str(exc_info.value)


def test_build_document_parser_rejects_unknown_backend() -> None:
    with pytest.raises(RuntimeError) as exc_info:
        build_document_parser(Settings(parser_backend="mystery-backend"))

    assert "Unknown parser backend" in str(exc_info.value)
    assert "mystery-backend" in str(exc_info.value)


def test_docling_document_parser_requires_configured_converter() -> None:
    parser = DoclingDocumentParser()

    with pytest.raises(RuntimeError) as exc_info:
        parser.parse(
            ParseRequest(
                document_id="11111111-1111-1111-1111-111111111111",
                object_key="documents/sample.pdf",
                content_type="application/pdf",
                profile="local-cpu",
                parser_backend="docling-local",
            )
        )

    assert "storage root" in str(exc_info.value)


def test_docling_document_parser_raises_when_local_storage_root_is_missing_file(tmp_path: Path) -> None:
    parser = DoclingDocumentParser(storage_root=tmp_path)

    with pytest.raises(RuntimeError) as exc_info:
        parser.parse(
            ParseRequest(
                document_id="11111111-1111-1111-1111-111111111111",
                object_key="documents/missing.pdf",
                content_type="application/pdf",
                profile="local-cpu",
                parser_backend="docling-local",
            )
        )

    message = str(exc_info.value)
    assert "documents/missing.pdf" in message
    assert "not found" in message


def test_docling_document_parser_raises_clear_error_when_docling_package_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "documents" / "sample.pdf"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"%PDF-1.4")
    parser = DoclingDocumentParser(storage_root=tmp_path)

    def _raise_import_error(_module_name: str):
        raise ImportError("docling unavailable")

    monkeypatch.setattr(docling_backend, "import_module", _raise_import_error)

    with pytest.raises(RuntimeError) as exc_info:
        parser.parse(
            ParseRequest(
                document_id="11111111-1111-1111-1111-111111111111",
                object_key="documents/sample.pdf",
                content_type="application/pdf",
                profile="local-cpu",
                parser_backend="docling-local",
            )
        )

    assert "docling package" in str(exc_info.value).lower()


def test_docling_document_parser_normalizes_pages_and_tables_from_local_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "documents" / "sample.pdf"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"%PDF-1.4")

    class FakePage:
        def __init__(self, page_no: int, markdown: str) -> None:
            self.page_no = page_no
            self._markdown = markdown

        def export_to_markdown(self) -> str:
            return self._markdown

    class FakeTable:
        def __init__(self, page_no: int, markdown: str, bbox: tuple[float, float, float, float]) -> None:
            self.page_no = page_no
            self._markdown = markdown
            self.prov = [SimpleNamespace(page_no=page_no, bbox=SimpleNamespace(l=bbox[0], t=bbox[1], r=bbox[2], b=bbox[3]))]

        def export_to_markdown(self) -> str:
            return self._markdown

    class FakeDocument:
        def __init__(self) -> None:
            self.pages = {1: FakePage(1, "Page one")}
            self.tables = [FakeTable(1, "|a|b|", (0.0, 0.0, 10.0, 20.0))]

    class FakeDocumentConverter:
        def convert(self, source: Path):
            assert source == source_file
            return SimpleNamespace(document=FakeDocument())

    monkeypatch.setattr(
        docling_backend,
        "import_module",
        lambda _module_name: SimpleNamespace(DocumentConverter=FakeDocumentConverter),
    )

    parser = DoclingDocumentParser(storage_root=tmp_path)
    artifact = parser.parse(
        ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/sample.pdf",
            content_type="application/pdf",
            profile="local-cpu",
            parser_backend="docling-local",
        )
    )

    assert [page.page_number for page in artifact.pages] == [1]
    assert artifact.pages[0].text == "Page one"
    assert [table.page_number for table in artifact.tables] == [1]
    assert artifact.tables[0].bbox == [0.0, 0.0, 10.0, 20.0]
    assert artifact.provenance.parser_backend == "docling-local"
    assert artifact.provenance.profile == "local-cpu"


def test_docling_document_parser_surfaces_underlying_conversion_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "documents" / "broken.pdf"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"%PDF-1.4 broken")

    class FakeDocumentConverter:
        def convert(self, _source: Path):
            raise ValueError("malformed document stream")

    monkeypatch.setattr(
        docling_backend,
        "import_module",
        lambda _module_name: SimpleNamespace(DocumentConverter=FakeDocumentConverter),
    )

    parser = DoclingDocumentParser(storage_root=tmp_path)

    with pytest.raises(RuntimeError) as exc_info:
        parser.parse(
            ParseRequest(
                document_id="11111111-1111-1111-1111-111111111111",
                object_key="documents/broken.pdf",
                content_type="application/pdf",
                profile="local-cpu",
                parser_backend="docling-local",
            )
        )

    message = str(exc_info.value)
    assert "documents/broken.pdf" in message
    assert "malformed document stream" in message


def test_docling_document_parser_uses_local_source_path_when_provided(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    local_file = tmp_path / "materialized.pdf"
    local_file.write_bytes(b"%PDF-1.4")

    class FakePage:
        def __init__(self, page_no: int, markdown: str) -> None:
            self.page_no = page_no
            self._markdown = markdown

        def export_to_markdown(self) -> str:
            return self._markdown

    class FakeDocument:
        def __init__(self) -> None:
            self.pages = {1: FakePage(1, "Materialized page")}
            self.tables = []

    class FakeDocumentConverter:
        def convert(self, source: Path):
            assert Path(source) == local_file
            return SimpleNamespace(document=FakeDocument())

    monkeypatch.setattr(
        docling_backend,
        "import_module",
        lambda _module_name: SimpleNamespace(DocumentConverter=FakeDocumentConverter),
    )

    parser = DoclingDocumentParser(storage_root=tmp_path / "unused")
    artifact = parser.parse(
        ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="ignored/by/materialized/path.pdf",
            content_type="application/pdf",
            profile="local-cpu",
            parser_backend="docling-local",
            local_source_path=str(local_file),
        )
    )

    assert artifact.pages[0].text == "Materialized page"
    assert artifact.provenance.parser_backend == "docling-local"
    assert artifact.provenance.profile == "local-cpu"


def test_docling_document_parser_falls_back_to_storage_root_when_no_local_source_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "documents" / "fallback.pdf"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"%PDF-1.4")

    class FakePage:
        def __init__(self, page_no: int, markdown: str) -> None:
            self.page_no = page_no
            self._markdown = markdown

        def export_to_markdown(self) -> str:
            return self._markdown

    class FakeDocument:
        def __init__(self) -> None:
            self.pages = {1: FakePage(1, "Fallback page")}
            self.tables = []

    class FakeDocumentConverter:
        def convert(self, source: Path):
            assert Path(source) == source_file
            return SimpleNamespace(document=FakeDocument())

    monkeypatch.setattr(
        docling_backend,
        "import_module",
        lambda _module_name: SimpleNamespace(DocumentConverter=FakeDocumentConverter),
    )

    parser = DoclingDocumentParser(storage_root=tmp_path)
    artifact = parser.parse(
        ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/fallback.pdf",
            content_type="application/pdf",
            profile="local-cpu",
            parser_backend="docling-local",
        )
    )

    assert artifact.pages[0].text == "Fallback page"
    assert artifact.provenance.parser_backend == "docling-local"
