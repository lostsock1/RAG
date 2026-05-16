from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

import app.services.parsers.docling_backend as docling_backend
from app.core.config import Settings
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance
from app.services.parsers.base import ParseRequest
from app.services.parsers.docling_backend import DoclingDocumentParser
from app.services.parsers.factory import build_document_parser
from app.services.parsers.remote_backend import RemoteDocumentParser


def _build_artifact(*, profile: str = "source-profile") -> ParsedArtifact:
    return ParsedArtifact(
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        pages=[ParsedPage(page_number=1, text="Example", blocks=[])],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 1, 1], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="stub", parser_version="1.0", profile=profile),
    )


def test_remote_document_parser_overrides_profile_from_request() -> None:
    parser = RemoteDocumentParser(invoke_remote_parser=lambda request: _build_artifact())

    artifact = parser.parse(
        ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/sample.txt",
            content_type="text/plain",
            profile="gpu-local",
        )
    )

    assert artifact.provenance.parser_backend == "remote"
    assert artifact.provenance.profile == "gpu-local"


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


def test_build_document_parser_rejects_docling_with_seaweedfs_storage(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError) as exc_info:
        build_document_parser(
            Settings(
                parser_backend="docling",
                storage_backend="seaweedfs",
                local_storage_dir=str(tmp_path),
            )
        )

    message = str(exc_info.value)
    assert "SeaweedFS object storage is not yet compatible with the local Docling parser runtime" in message
    assert "current parser expects files readable from local disk" in message
    assert "use local storage for now, or implement remote object-read parsing first" in message


def test_build_document_parser_rejects_remote_backend_until_supported() -> None:
    with pytest.raises(RuntimeError) as exc_info:
        build_document_parser(Settings(parser_backend="remote"))

    assert "not yet supported" in str(exc_info.value)
    assert "remote" in str(exc_info.value)


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
                profile="cpu-local",
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
                profile="cpu-local",
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
                profile="cpu-local",
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
            profile="cpu-local",
        )
    )

    assert [page.page_number for page in artifact.pages] == [1]
    assert artifact.pages[0].text == "Page one"
    assert [table.page_number for table in artifact.tables] == [1]
    assert artifact.tables[0].bbox == [0.0, 0.0, 10.0, 20.0]
    assert artifact.provenance.parser_backend == "docling"
    assert artifact.provenance.profile == "cpu-local"


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
                profile="cpu-local",
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
            local_source_path=str(local_file),
        )
    )

    assert artifact.pages[0].text == "Materialized page"
    assert artifact.provenance.parser_backend == "docling"
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
        )
    )

    assert artifact.pages[0].text == "Fallback page"
