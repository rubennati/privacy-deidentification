"""Integration tests for OCR/Text Workstation v1 routing and persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.api.ocr import provide_ocr_adapter
from app.config import Settings
from app.main import app
from app.services.ocr_adapters import OcrUnavailableError
from app.services.pdf_renderer import get_pdf_renderer


class FakeOcrAdapter:
    def __init__(self) -> None:
        self.outputs: list[str] = []
        self.calls: list[Path] = []
        self.unavailable = False

    def extract_text(self, image_path: Path) -> str:
        self.calls.append(image_path)
        if self.unavailable:
            raise OcrUnavailableError
        return self.outputs[len(self.calls) - 1]

    def tool_versions(self) -> dict[str, str]:
        return {"paddleocr": "test"}


class FakePdfRenderer:
    def __init__(self) -> None:
        self.calls: list[int] = []
        self.output_directories: list[Path] = []
        self.fail = False

    def render_page(self, pdf_path: Path, page_number: int, output_dir: Path) -> Path:
        self.calls.append(page_number)
        self.output_directories.append(output_dir)
        if self.fail:
            raise RuntimeError("simulated rendering failure")
        rendered = output_dir / f"page-{page_number}.png"
        rendered.write_bytes(b"fake rendered page")
        return rendered


@pytest.fixture(autouse=True)
def _allow_larger_ocr_fixtures(settings: Settings) -> None:
    settings.max_upload_bytes = 2 * 1024 * 1024


@pytest.fixture
def ocr_fakes(client: TestClient) -> Iterator[tuple[FakeOcrAdapter, FakePdfRenderer]]:
    adapter = FakeOcrAdapter()
    renderer = FakePdfRenderer()
    app.dependency_overrides[provide_ocr_adapter] = lambda: adapter
    app.dependency_overrides[get_pdf_renderer] = lambda: renderer
    yield adapter, renderer


def _upload(client: TestClient, name: str, content: bytes, content_type: str) -> dict[str, object]:
    response = client.post("/api/uploads", files={"file": (name, content, content_type)})
    assert response.status_code == 201
    return response.json()


def _upload_and_audit(
    client: TestClient, name: str, content: bytes, content_type: str
) -> tuple[dict[str, object], dict[str, object]]:
    upload = _upload(client, name, content, content_type)
    response = client.post(f"/api/documents/{upload['id']}/audit")
    assert response.status_code == 201
    return upload, response.json()


def _pdf_pages_bytes(*page_texts: str | None) -> bytes:
    writer = PdfWriter()
    for text in page_texts:
        page = writer.add_blank_page(width=200, height=200)
        if text is not None:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {NameObject("/F1"): writer._add_object(font)}
                    )
                }
            )
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _docx_bytes(*paragraphs: str) -> bytes:
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _docx_with_table_bytes() -> bytes:
    """A paragraph, a 2x2 table, then a paragraph — to exercise ordered table extraction."""
    document = DocxDocument()
    document.add_paragraph("Intro")
    table = document.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "R1C1"
    table.rows[0].cells[1].text = "R1C2"
    table.rows[1].cells[0].text = "R2C1"
    table.rows[1].cells[1].text = "R2C2"
    document.add_paragraph("Outro")
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _image_bytes(image_format: str, size: tuple[int, int] = (10, 10)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color="white").save(buffer, format=image_format)
    return buffer.getvalue()


def _artifact_path(upload_dir: Path, document_id: object, artifact_id: object) -> Path:
    return upload_dir / "artifacts" / str(document_id) / f"{artifact_id}.json"


def test_pdf_text_layer_creates_text_artifact_without_ocr(
    client: TestClient,
    upload_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, renderer = ocr_fakes
    upload, audit = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Digital text"), "application/pdf"
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    artifact = response.json()
    content = artifact["content"]
    assert artifact["artifact_type"] == "text_result"
    assert artifact["station"] == "ocr"
    assert artifact["input_artifact_id"] == upload["original_artifact"]["id"]
    assert artifact["input_audit_artifact_id"] == audit["id"]
    assert content["source"] == "pdf_text_layer"
    assert content["text"] == "Digital text"
    assert content["text_char_count"] == len(content["text"])
    assert content["pages"] == [
        {
            "page_number": 1,
            "source": "pdf_text_layer",
            "has_text_layer": True,
            "ocr_used": False,
            "text": "Digital text",
            "text_char_count": len("Digital text"),
        }
    ]
    assert content["tool_versions"]["pypdf"]
    assert adapter.calls == []
    assert renderer.calls == []
    assert _artifact_path(upload_dir, upload["id"], artifact["id"]).is_file()


def test_mixed_pdf_routes_each_page_and_preserves_order(
    client: TestClient,
    upload_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, renderer = ocr_fakes
    adapter.outputs = ["Scan two", "Scan three"]
    upload, _ = _upload_and_audit(
        client,
        "mixed.pdf",
        _pdf_pages_bytes("Digital one", None, None),
        "application/pdf",
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    content = response.json()["content"]
    assert content["source"] == "pdf_mixed"
    assert content["text"] == "Digital one\n\nScan two\n\nScan three"
    assert [page["source"] for page in content["pages"]] == [
        "pdf_text_layer",
        "paddleocr",
        "paddleocr",
    ]
    assert renderer.calls == [2, 3]
    assert [path.name for path in adapter.calls] == ["page-2.png", "page-3.png"]
    assert all(path.parent == Path("/tmp") for path in renderer.output_directories)
    assert all(upload_dir not in path.parents for path in adapter.calls)
    assert all(not path.exists() for path in adapter.calls)
    artifact_directory = upload_dir / "artifacts" / str(upload["id"])
    assert all(path.suffix == ".json" for path in artifact_directory.rglob("*"))


def test_docx_extracts_paragraphs_without_ocr(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, renderer = ocr_fakes
    upload, _ = _upload_and_audit(
        client,
        "document.docx",
        _docx_bytes("First", "Second"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    content = response.json()["content"]
    assert content["source"] == "docx_text"
    assert content["text"] == "First\nSecond"
    assert content["pages"] == []
    assert adapter.calls == []
    assert renderer.calls == []


def test_docx_extracts_table_cells_in_document_order(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, renderer = ocr_fakes
    upload, _ = _upload_and_audit(
        client,
        "tables.docx",
        _docx_with_table_bytes(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    content = response.json()["content"]
    assert content["source"] == "docx_text"
    # Deterministic order: leading paragraph, table rows (cells tab-joined, rows newline-joined),
    # trailing paragraph. Table cell text must be present — paragraph-only extraction dropped it.
    assert content["text"] == "Intro\nR1C1\tR1C2\nR2C1\tR2C2\nOutro"
    assert content["text_char_count"] == len(content["text"])
    assert content["pages"] == []
    assert adapter.calls == []
    assert renderer.calls == []


@pytest.mark.parametrize(
    ("extension", "mime_type", "image_format"),
    [("png", "image/png", "PNG"), ("jpg", "image/jpeg", "JPEG")],
)
def test_image_uses_ocr_once(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
    extension: str,
    mime_type: str,
    image_format: str,
) -> None:
    adapter, renderer = ocr_fakes
    adapter.outputs = ["Image text"]
    upload, _ = _upload_and_audit(
        client, f"image.{extension}", _image_bytes(image_format), mime_type
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    content = response.json()["content"]
    assert content["source"] == "paddleocr"
    assert content["text"] == "Image text"
    assert content["pages"][0]["page_number"] == 1
    assert len(adapter.calls) == 1
    assert renderer.calls == []


def test_missing_audit_returns_409(
    client: TestClient, ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer]
) -> None:
    upload = _upload(client, "blank.pdf", _pdf_pages_bytes(None), "application/pdf")

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 409


def test_legacy_sidecar_without_original_artifact_returns_409(
    client: TestClient,
    upload_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload = _upload(client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf")
    document_id = str(upload["id"])
    metadata_path = upload_dir / f"{document_id}.meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("original_artifact")
    metadata.pop("sha256")
    metadata.pop("detected_mime_type")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    response = client.post(f"/api/documents/{document_id}/ocr")

    assert response.status_code == 409


def test_get_without_text_artifact_returns_404(client: TestClient) -> None:
    upload, _ = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf"
    )

    response = client.get(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 404


def test_get_returns_latest_text_artifact(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload, _ = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf"
    )
    timestamps = iter(["2026-07-01T10:00:00.000001Z", "2026-07-01T10:00:00.000002Z"])
    monkeypatch.setattr("app.services.ocr_service._now_utc_iso", lambda: next(timestamps))
    first = client.post(f"/api/documents/{upload['id']}/ocr")
    second = client.post(f"/api/documents/{upload['id']}/ocr")

    response = client.get(f"/api/documents/{upload['id']}/ocr")

    assert first.status_code == 201
    assert second.status_code == 201
    assert response.status_code == 200
    assert response.json()["id"] == second.json()["id"]


def test_hash_mismatch_prevents_text_artifact(
    client: TestClient,
    upload_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, audit = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf"
    )
    original = upload["original_artifact"]
    assert isinstance(original, dict)
    (upload_dir / str(original["storage_filename"])).write_bytes(b"tampered")

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 409
    artifact_directory = upload_dir / "artifacts" / str(upload["id"])
    assert [path.stem for path in artifact_directory.glob("*.json")] == [str(audit["id"])]


def test_audit_input_artifact_mismatch_returns_409(
    client: TestClient,
    upload_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, audit = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf"
    )
    path = _artifact_path(upload_dir, upload["id"], audit["id"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["input_artifact_id"] = "f" * 32
    payload["content"]["input_artifact_id"] = "f" * 32
    path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 409


def test_inconsistent_pdf_audit_page_list_returns_409(
    client: TestClient,
    upload_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, audit = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf"
    )
    path = _artifact_path(upload_dir, upload["id"], audit["id"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["content"]["pages"][0]["page_number"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 409


def test_rendering_failure_returns_422(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, renderer = ocr_fakes
    renderer.fail = True
    upload, _ = _upload_and_audit(
        client, "blank.pdf", _pdf_pages_bytes(None), "application/pdf"
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 422
    assert adapter.calls == []


def test_paddleocr_unavailable_returns_503(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, _ = ocr_fakes
    adapter.unavailable = True
    upload, _ = _upload_and_audit(
        client, "image.png", _image_bytes("PNG"), "image/png"
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 503


def test_corrupt_original_returns_422_after_integrity_validation(
    client: TestClient,
    upload_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf"
    )
    document_id = str(upload["id"])
    metadata_path = upload_dir / f"{document_id}.meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    original_path = upload_dir / metadata["original_artifact"]["storage_filename"]
    corrupt = b"%PDF-1.4 broken after audit"
    digest = hashlib.sha256(corrupt).hexdigest()
    original_path.write_bytes(corrupt)
    metadata["sha256"] = digest
    metadata["original_artifact"]["sha256"] = digest
    metadata["size"] = len(corrupt)
    metadata["original_artifact"]["size_bytes"] = len(corrupt)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    response = client.post(f"/api/documents/{document_id}/ocr")

    assert response.status_code == 422


def test_delete_removes_audit_and_text_artifacts(
    client: TestClient,
    upload_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf"
    )
    assert client.post(f"/api/documents/{upload['id']}/ocr").status_code == 201
    artifact_directory = upload_dir / "artifacts" / str(upload["id"])
    assert len(list(artifact_directory.glob("*.json"))) == 2

    response = client.delete(f"/api/documents/{upload['id']}")

    assert response.status_code == 204
    assert not artifact_directory.exists()
