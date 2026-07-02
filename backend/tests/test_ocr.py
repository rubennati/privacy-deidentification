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
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.api.ocr import provide_ocr_adapter
from app.config import Settings
from app.main import app
from app.services.ocr_adapters import OcrExtractionResult, OcrLineMetric, OcrUnavailableError
from app.services.pdf_renderer import get_pdf_renderer


class FakeOcrAdapter:
    def __init__(self) -> None:
        self.outputs: list[str] = []
        self.confidences: list[float | None] = []
        self.line_confidences: list[tuple[OcrLineMetric, ...]] = []
        self.calls: list[Path] = []
        self.unavailable = False

    def extract_text(self, image_path: Path) -> str:
        return self.extract_result(image_path).text

    def extract_result(self, image_path: Path) -> OcrExtractionResult:
        self.calls.append(image_path)
        if self.unavailable:
            raise OcrUnavailableError
        index = len(self.calls) - 1
        return OcrExtractionResult(
            text=self.outputs[index],
            confidence=self.confidences[index] if index < len(self.confidences) else None,
            line_confidences=(
                self.line_confidences[index] if index < len(self.line_confidences) else ()
            ),
        )

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


def _artifact_path(
    document_data_dir: Path, document_id: object, artifact_id: object
) -> Path:
    return document_data_dir / str(document_id) / "artifacts" / f"{artifact_id}.json"


def _set_audit_page_fields(
    document_data_dir: Path,
    document_id: object,
    audit_id: object,
    page_index: int,
    **fields: object,
) -> None:
    """Overwrite persisted audit page fields to stage a specific per-page routing decision."""
    path = _artifact_path(document_data_dir, document_id, audit_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["content"]["pages"][page_index].update(fields)
    path.write_text(json.dumps(payload), encoding="utf-8")


_GOOD_TEXT = "The quick brown fox jumps over the lazy dog near the calm winding river today"


def test_pdf_text_layer_creates_text_artifact_without_ocr(
    client: TestClient,
    document_data_dir: Path,
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
            "ocr_confidence": None,
            "ocr_line_confidences": [],
        }
    ]
    assert content["tool_versions"]["pypdf"]
    assert adapter.calls == []
    assert renderer.calls == []
    assert _artifact_path(document_data_dir, upload["id"], artifact["id"]).is_file()


def test_mixed_pdf_routes_each_page_and_preserves_order(
    client: TestClient,
    upload_dir: Path,
    document_data_dir: Path,
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
    artifact_directory = document_data_dir / str(upload["id"]) / "artifacts"
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
    adapter.confidences = [0.91]
    adapter.line_confidences = [(OcrLineMetric(1, 0.91, len("Image text")),)]
    upload, _ = _upload_and_audit(
        client, f"image.{extension}", _image_bytes(image_format), mime_type
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    content = response.json()["content"]
    assert content["source"] == "paddleocr"
    assert content["text"] == "Image text"
    assert content["pages"][0]["page_number"] == 1
    assert content["pages"][0]["ocr_confidence"] == 0.91
    assert content["pages"][0]["ocr_line_confidences"] == [
        {"line_index": 1, "confidence": 0.91, "text_char_count": len("Image text")}
    ]
    assert len(adapter.calls) == 1
    assert renderer.calls == []


def test_good_text_pdf_does_not_initialize_ocr(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, renderer = ocr_fakes
    upload, _ = _upload_and_audit(
        client, "good.pdf", _pdf_pages_bytes(_GOOD_TEXT), "application/pdf"
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    content = response.json()["content"]
    assert content["source"] == "pdf_text_layer"
    # A clean text-layer PDF never renders a page or touches the OCR adapter (no PaddleOCR init).
    assert adapter.calls == []
    assert renderer.calls == []


def test_broken_text_layer_page_routes_to_ocr(
    client: TestClient,
    document_data_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, renderer = ocr_fakes
    adapter.outputs = ["OCR recovered text"]
    upload, audit = _upload_and_audit(
        client, "broken.pdf", _pdf_pages_bytes("Digital text"), "application/pdf"
    )
    _set_audit_page_fields(
        document_data_dir,
        upload["id"],
        audit["id"],
        0,
        text_quality_status="BROKEN_TEXT_LAYER",
        needs_ocr=True,
        recommended_text_source="ocr",
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    content = response.json()["content"]
    assert content["source"] == "paddleocr"
    page = content["pages"][0]
    assert page["source"] == "paddleocr"
    assert page["ocr_used"] is True
    assert page["has_text_layer"] is False
    assert page["text"] == "OCR recovered text"
    assert renderer.calls == [1]
    assert len(adapter.calls) == 1


def test_empty_text_layer_page_routes_to_ocr(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, renderer = ocr_fakes
    adapter.outputs = ["Scanned page text"]
    adapter.confidences = [0.84]
    adapter.line_confidences = [(OcrLineMetric(1, 0.84, len("Scanned page text")),)]
    upload, _ = _upload_and_audit(
        client, "scan.pdf", _pdf_pages_bytes(None), "application/pdf"
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    content = response.json()["content"]
    assert content["source"] == "paddleocr"
    assert content["pages"][0]["ocr_used"] is True
    assert content["pages"][0]["ocr_confidence"] == 0.84
    assert content["pages"][0]["ocr_line_confidences"][0]["line_index"] == 1
    assert "text" not in content["pages"][0]["ocr_line_confidences"][0]
    assert content["text"] == "Scanned page text"
    assert content["pages"][0]["text"] == "Scanned page text"
    assert renderer.calls == [1]
    assert len(adapter.calls) == 1


def test_mixed_quality_pdf_routes_each_page(
    client: TestClient,
    document_data_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, renderer = ocr_fakes
    adapter.outputs = ["Broken page OCR", "Scanned page OCR"]
    upload, audit = _upload_and_audit(
        client, "mixed.pdf", _pdf_pages_bytes(_GOOD_TEXT, _GOOD_TEXT, None), "application/pdf"
    )
    # Page 1 stays GOOD (text layer), page 2 is corrupted to BROKEN, page 3 is empty — the two
    # OCR-required pages must be rendered while the good page is not.
    _set_audit_page_fields(
        document_data_dir,
        upload["id"],
        audit["id"],
        1,
        text_quality_status="BROKEN_TEXT_LAYER",
        needs_ocr=True,
        recommended_text_source="ocr",
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    content = response.json()["content"]
    assert content["source"] == "pdf_mixed"
    assert [page["source"] for page in content["pages"]] == [
        "pdf_text_layer",
        "paddleocr",
        "paddleocr",
    ]
    assert renderer.calls == [2, 3]
    assert len(adapter.calls) == 2


def test_ocr_required_page_without_runtime_returns_503(
    client: TestClient,
    document_data_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, _ = ocr_fakes
    adapter.unavailable = True
    upload, audit = _upload_and_audit(
        client, "broken.pdf", _pdf_pages_bytes("Digital text"), "application/pdf"
    )
    _set_audit_page_fields(
        document_data_dir,
        upload["id"],
        audit["id"],
        0,
        text_quality_status="BROKEN_TEXT_LAYER",
        needs_ocr=True,
        recommended_text_source="ocr",
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 503
    # The broken text layer is never silently used as a result: no text_result artifact is written.
    artifact_directory = document_data_dir / str(upload["id"]) / "artifacts"
    assert [path.stem for path in artifact_directory.glob("*.json")] == [str(audit["id"])]


def test_legacy_audit_without_quality_fields_uses_text_layer(
    client: TestClient,
    document_data_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, renderer = ocr_fakes
    upload, audit = _upload_and_audit(
        client, "legacy.pdf", _pdf_pages_bytes("Digital text"), "application/pdf"
    )
    path = _artifact_path(document_data_dir, upload["id"], audit["id"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "text_quality_status",
        "text_quality_score",
        "text_quality_reasons",
        "recommended_text_source",
        "needs_ocr",
    ):
        payload["content"]["pages"][0].pop(key, None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    content = response.json()["content"]
    # Audits predating the quality gate carry no needs_ocr, so routing falls back to has_text_layer.
    assert content["source"] == "pdf_text_layer"
    assert adapter.calls == []
    assert renderer.calls == []


def test_missing_audit_returns_409(
    client: TestClient, ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer]
) -> None:
    upload = _upload(client, "blank.pdf", _pdf_pages_bytes(None), "application/pdf")

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 409


def test_legacy_metadata_without_original_artifact_returns_409(
    client: TestClient,
    document_data_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload = _upload(client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf")
    document_id = str(upload["id"])
    metadata_path = document_data_dir / document_id / "document.json"
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
    document_data_dir: Path,
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
    artifact_directory = document_data_dir / str(upload["id"]) / "artifacts"
    assert [path.stem for path in artifact_directory.glob("*.json")] == [str(audit["id"])]


def test_audit_input_artifact_mismatch_returns_409(
    client: TestClient,
    document_data_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, audit = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf"
    )
    path = _artifact_path(document_data_dir, upload["id"], audit["id"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["input_artifact_id"] = "f" * 32
    payload["content"]["input_artifact_id"] = "f" * 32
    path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 409


def test_inconsistent_pdf_audit_page_list_returns_409(
    client: TestClient,
    document_data_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, audit = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf"
    )
    path = _artifact_path(document_data_dir, upload["id"], audit["id"])
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
    document_data_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf"
    )
    document_id = str(upload["id"])
    metadata_path = document_data_dir / document_id / "document.json"
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


def _pdf_two_column_table_bytes() -> bytes:
    """Synthetic single-page offer: two side-by-side blocks and a table. No real data.

    Text runs are placed at absolute page coordinates so pypdf's layout extraction can reconstruct
    columns and table rows; the default extraction linearises them.
    """
    runs = [
        (40, 770, "KOSTENVORANSCHLAG"),
        (40, 730, "AUFTRAGNEHMER"), (320, 730, "AUFTRAGGEBER"),
        (40, 712, "Sanierungsbau Perchtoldsdorf GmbH"),
        (320, 712, "Herr Dipl.-Ing. Franz Hubermayr"),
        (40, 694, "Lindenstrasse 42"), (320, 694, "Rosengasse 7/12"),
        (40, 640, "Angebot Nr.: KV-2026-0417"), (320, 640, "Datum: 01.07.2026"),
        (40, 590, "Pos."), (90, 590, "Leistung"), (330, 590, "Menge"),
        (390, 590, "Einheit"), (450, 590, "Einzelpreis"), (530, 590, "Gesamt"),
        (40, 572, "1"), (90, 572, "Abbrucharbeiten Innenwaende"), (330, 572, "45"),
        (390, 572, "m2"), (450, 572, "38,00"), (530, 572, "1.710,00"),
        (40, 554, "2"), (90, 554, "Fassadendaemmung"), (330, 554, "180"),
        (390, 554, "m2"), (450, 554, "92,00"), (530, 554, "16.560,00"),
    ]
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    data = "".join(f"BT /F1 10 Tf {x} {y} Td ({text}) Tj ET\n" for x, y, text in runs)
    stream = DecodedStreamObject()
    stream.set_data(data.encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _line_with(text: str, *tokens: str) -> str | None:
    return next(
        (line for line in text.split("\n") if all(token in line for token in tokens)),
        None,
    )


def test_pdf_text_layer_produces_layout_text_result(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, renderer = ocr_fakes
    fixture = _pdf_two_column_table_bytes()
    upload, _ = _upload_and_audit(client, "offer.pdf", fixture, "application/pdf")

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    content = response.json()["content"]
    # Canonical text is exactly the unchanged default extraction — the offset-stable PII input.
    expected_canonical = "\n\n".join(
        page.extract_text() or "" for page in PdfReader(BytesIO(fixture)).pages
    )
    assert content["text"] == expected_canonical
    layout = content["layout_text_result"]
    assert layout is not None
    # The layout rendering is a distinct, additive view — not the canonical text.
    assert layout != content["text"]
    # Two-column block stays side by side on one line.
    assert _line_with(layout, "AUFTRAGNEHMER", "AUFTRAGGEBER") is not None
    # Table header and its first value row each stay on a single readable line (no line-by-line
    # collapse of header vs values).
    assert _line_with(layout, "Pos.", "Leistung", "Gesamt") is not None
    assert _line_with(layout, "Abbrucharbeiten Innenwaende", "1.710,00") is not None
    # A clean text-layer PDF still never touches OCR.
    assert adapter.calls == []
    assert renderer.calls == []


def test_layout_text_result_absent_for_docx(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client,
        "document.docx",
        _docx_bytes("First", "Second"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    assert response.json()["content"]["layout_text_result"] is None


def test_layout_text_result_absent_for_image(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, _ = ocr_fakes
    adapter.outputs = ["Image text"]
    upload, _ = _upload_and_audit(client, "image.png", _image_bytes("PNG"), "image/png")

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    assert response.json()["content"]["layout_text_result"] is None


def test_layout_text_result_marks_ocr_pages_and_page_boundaries(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, _ = ocr_fakes
    adapter.outputs = ["Scanned page two text"]
    upload, _ = _upload_and_audit(
        client, "mixed.pdf", _pdf_pages_bytes(_GOOD_TEXT, None), "application/pdf"
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    layout = response.json()["content"]["layout_text_result"]
    assert layout is not None
    # Page 1 (text layer) contributes a layout rendering.
    assert _GOOD_TEXT.split()[0] in layout
    # Page boundary is visible and the OCR page is marked as not reconstructed, falling back to its
    # linear text.
    assert "----- page 2 -----" in layout
    assert "[page 2: layout not reconstructed]" in layout
    assert "Scanned page two text" in layout


def test_legacy_text_artifact_without_additive_fields_remains_valid(
    client: TestClient,
    document_data_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Digital text"), "application/pdf"
    )
    created = client.post(f"/api/documents/{upload['id']}/ocr").json()
    path = _artifact_path(document_data_dir, upload["id"], created["id"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Simulate a legacy artifact written before this field existed.
    payload["content"].pop("layout_text_result", None)
    for page in payload["content"]["pages"]:
        page.pop("ocr_confidence", None)
        page.pop("ocr_line_confidences", None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.get(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 200
    assert response.json()["content"]["layout_text_result"] is None
    page = response.json()["content"]["pages"][0]
    assert page["ocr_confidence"] is None
    assert page["ocr_line_confidences"] == []


def _pdf_contact_blocks_and_table_bytes() -> bytes:
    """Synthetic single-page offer: two multi-line contact blocks and a table. No real data.

    The left block (x=40) and right block (x=320) each carry several lines so a reading-order
    reconstruction can be checked for "left block fully, then right block fully" rather than only a
    single shared row. Line/company/street names are invented and structurally similar to, but not
    copied from, real documents.
    """
    runs = [
        (40, 770, "Sanierungsbau Perchtoldsdorf GmbH"),
        (320, 770, "Herr Dipl.-Ing. Franz Hubermayr"),
        (40, 752, "Lindenstrasse 42"),
        (320, 752, "Anna Hubermayr geb. Steininger"),
        (40, 734, "2380 Perchtoldsdorf Oesterreich"),
        (320, 734, "Rosengasse 7/12"),
        (40, 716, "Tel: +43 660 1234567"),
        (320, 716, "2340 Moedling Oesterreich"),
        (40, 698, "office@example-contractor.at"),
        (320, 698, "Tel: +43 699 8765432"),
        (40, 680, "UID: ATU12345678"),
        (320, 680, "franz.hubermayr@example.at"),
        (320, 662, "Geburtsdatum: 14.03.1978"),
        (40, 600, "Pos."), (90, 600, "Leistung"), (330, 600, "Menge"),
        (390, 600, "Einheit"), (450, 600, "Einzelpreis"), (530, 600, "Gesamt"),
        (40, 582, "1"), (90, 582, "Abbrucharbeiten Innenwaende"), (330, 582, "45"),
        (390, 582, "m2"), (450, 582, "38,00"), (530, 582, "1710,00"),
        (40, 564, "2"), (90, 564, "Fassadendaemmung"), (330, 564, "180"),
        (390, 564, "m2"), (450, 564, "92,00"), (530, 564, "16560,00"),
    ]
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    data = "".join(f"BT /F1 10 Tf {x} {y} Td ({text}) Tj ET\n" for x, y, text in runs)
    stream = DecodedStreamObject()
    stream.set_data(data.encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pii_input_text_generated_for_pdf_text_layer(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, renderer = ocr_fakes
    fixture = _pdf_contact_blocks_and_table_bytes()
    upload, _ = _upload_and_audit(client, "offer.pdf", fixture, "application/pdf")

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    content = response.json()["content"]
    pii_input_text = content["pii_input_text"]
    assert pii_input_text is not None
    assert "[BLOCK: left]" in pii_input_text
    assert "[BLOCK: right]" in pii_input_text
    assert "[TABLE]" in pii_input_text
    assert adapter.calls == []
    assert renderer.calls == []


def test_pii_input_text_left_block_fully_before_right_block(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client, "offer.pdf", _pdf_contact_blocks_and_table_bytes(), "application/pdf"
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    pii_input_text = response.json()["content"]["pii_input_text"]
    left_index = pii_input_text.index("[BLOCK: left]")
    right_index = pii_input_text.index("[BLOCK: right]")
    table_index = pii_input_text.index("[TABLE]")
    # Whole left block precedes the whole right block, which precedes the table — not an
    # X/Y-interleaved dump of both columns.
    assert left_index < right_index < table_index


def test_pii_input_text_keeps_contractor_lines_in_left_block_only(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client, "offer.pdf", _pdf_contact_blocks_and_table_bytes(), "application/pdf"
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    pii_input_text = response.json()["content"]["pii_input_text"]
    left_index = pii_input_text.index("[BLOCK: left]")
    right_index = pii_input_text.index("[BLOCK: right]")
    left_segment = pii_input_text[left_index:right_index]
    right_segment = pii_input_text[right_index:]
    # A left-column line lands in the left block and never among the right block's lines.
    assert "Lindenstrasse 42" in left_segment
    assert "Lindenstrasse 42" not in right_segment


def test_pii_input_text_keeps_customer_lines_in_right_block(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client, "offer.pdf", _pdf_contact_blocks_and_table_bytes(), "application/pdf"
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    pii_input_text = response.json()["content"]["pii_input_text"]
    right_index = pii_input_text.index("[BLOCK: right]")
    table_index = pii_input_text.index("[TABLE]")
    right_segment = pii_input_text[right_index:table_index]
    assert "Herr Dipl.-Ing. Franz Hubermayr" in right_segment
    assert "Anna Hubermayr geb. Steininger" in right_segment


def test_pii_input_text_table_rows_reconstructed_row_wise(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client, "offer.pdf", _pdf_contact_blocks_and_table_bytes(), "application/pdf"
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    pii_input_text = response.json()["content"]["pii_input_text"]
    assert _line_with(pii_input_text, "Pos.", "Leistung", "Gesamt") is not None
    assert _line_with(pii_input_text, "Abbrucharbeiten Innenwaende", "1710,00") is not None


def test_pii_input_text_does_not_change_canonical_text(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    fixture = _pdf_contact_blocks_and_table_bytes()
    upload, _ = _upload_and_audit(client, "offer.pdf", fixture, "application/pdf")

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    content = response.json()["content"]
    expected_canonical = "\n\n".join(
        page.extract_text() or "" for page in PdfReader(BytesIO(fixture)).pages
    )
    assert content["text"] == expected_canonical


def test_pii_input_text_does_not_affect_layout_text_result(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client, "offer.pdf", _pdf_two_column_table_bytes(), "application/pdf"
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    content = response.json()["content"]
    # Both additive fields are produced independently for the same document; pii_input_text does
    # not replace or alter the existing layout_text_result behaviour.
    assert content["pii_input_text"] is not None
    layout = content["layout_text_result"]
    assert layout is not None
    assert _line_with(layout, "AUFTRAGNEHMER", "AUFTRAGGEBER") is not None
    assert _line_with(layout, "Pos.", "Leistung", "Gesamt") is not None


def test_pii_input_text_absent_for_docx(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client,
        "document.docx",
        _docx_bytes("First", "Second"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    assert response.json()["content"]["pii_input_text"] is None


def test_pii_input_text_absent_for_image(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, _ = ocr_fakes
    adapter.outputs = ["Image text"]
    upload, _ = _upload_and_audit(client, "image.png", _image_bytes("PNG"), "image/png")

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    assert response.json()["content"]["pii_input_text"] is None


def test_pii_input_text_marks_ocr_pages_and_page_boundaries(
    client: TestClient,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    adapter, _ = ocr_fakes
    adapter.outputs = ["Scanned page two text"]
    upload, _ = _upload_and_audit(
        client, "mixed.pdf", _pdf_pages_bytes(_GOOD_TEXT, None), "application/pdf"
    )

    response = client.post(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 201
    pii_input_text = response.json()["content"]["pii_input_text"]
    assert pii_input_text is not None
    assert "[PAGE 2]" in pii_input_text
    assert "[page 2: pii_input_text not reconstructed]" in pii_input_text
    assert "Scanned page two text" in pii_input_text


def test_legacy_text_artifact_without_pii_input_text_field_remains_valid(
    client: TestClient,
    document_data_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Digital text"), "application/pdf"
    )
    created = client.post(f"/api/documents/{upload['id']}/ocr").json()
    path = _artifact_path(document_data_dir, upload["id"], created["id"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Simulate a legacy artifact written before this field existed.
    payload["content"].pop("pii_input_text", None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.get(f"/api/documents/{upload['id']}/ocr")

    assert response.status_code == 200
    assert response.json()["content"]["pii_input_text"] is None


def test_delete_removes_audit_and_text_artifacts(
    client: TestClient,
    document_data_dir: Path,
    ocr_fakes: tuple[FakeOcrAdapter, FakePdfRenderer],
) -> None:
    upload, _ = _upload_and_audit(
        client, "text.pdf", _pdf_pages_bytes("Text"), "application/pdf"
    )
    assert client.post(f"/api/documents/{upload['id']}/ocr").status_code == 201
    artifact_directory = document_data_dir / str(upload["id"]) / "artifacts"
    assert len(list(artifact_directory.glob("*.json"))) == 2

    response = client.delete(f"/api/documents/{upload['id']}")

    assert response.status_code == 204
    assert not artifact_directory.exists()
