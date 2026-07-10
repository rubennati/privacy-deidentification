"""Unit and API tests for the OCR Output Contract v1 / Document Text Package (ADR-0027).

All data here is synthetic. Builder/validator tests exercise ``build_document_text_package`` and
``evaluate_contract_status`` directly against hand-built ``TextContent``/``TextArtifact``
fixtures — no private corpus, no OCR runtime, and no raw document text in any assertion. API tests
drive the new ``GET /api/documents/{id}/text-package`` endpoint through a synthetic text-layer PDF,
mirroring the fixtures already established in ``test_ocr.py``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.api.ocr import provide_ocr_adapter
from app.config import Settings
from app.main import app
from app.schemas import (
    DocumentTextPackageV1,
    DocumentTextPackageWarning,
    DocumentTextSourceV1,
    ReadingTextMapSegment,
    StructuredContent,
    StructuredContentSummary,
    StructuredField,
    StructuredPageContent,
    StructuredSpan,
    TextArtifact,
    TextContent,
    TextPageResult,
)
from app.services.document_text_package import build_document_text_package, evaluate_contract_status
from app.services.ocr_quality import build_quality_evidence
from app.services.pdf_renderer import get_pdf_renderer
from app.services.reading_text import ReadingTextResult

_KNOWN_WARNING_CODES = frozenset(get_args(DocumentTextPackageWarning))


def _hex_id(label: str) -> str:
    """A deterministic, always-valid 32-char lowercase hex id derived from a readable label."""
    return hashlib.sha256(label.encode()).hexdigest()[:32]


_DOCUMENT_ID = _hex_id("document")
_ORIGINAL_ARTIFACT_ID = _hex_id("original")
_AUDIT_ARTIFACT_ID = _hex_id("audit")
_TEXT_ARTIFACT_ID = _hex_id("text-artifact")
_RAW_TEXT = "Hello world."


# --- Shared synthetic fixtures ------------------------------------------------------------------


def _structured_content(raw_text: str) -> StructuredContent:
    """A minimal, schema-valid structured field spanning the first two words of ``raw_text``."""
    label = raw_text.split(" ", 1)[0]
    label_end = len(label)
    value = raw_text[label_end + 1 :].split(".", 1)[0]
    value_start = label_end + 1
    value_end = value_start + len(value)
    field = StructuredField(
        field_id="field-p1-1",
        page_number=1,
        label=label,
        label_span=StructuredSpan(
            canonical_start=0, canonical_end=label_end, page_start=0, page_end=label_end
        ),
        value_span=StructuredSpan(
            canonical_start=value_start,
            canonical_end=value_end,
            page_start=value_start,
            page_end=value_end,
        ),
        confidence=0.9,
        source="canonical_text",
    )
    page = StructuredPageContent(
        page_number=1, fields=[field], source="canonical_text", confidence=0.9
    )
    return StructuredContent(
        pages=[page],
        summary=StructuredContentSummary(
            page_count=1, table_count=0, field_count=1, section_count=0
        ),
        flags=["span_backed"],
    )


def _build_text_content(
    *,
    raw_text: str = _RAW_TEXT,
    include_canonical: bool = True,
    include_layout: bool = True,
    include_structured: bool = True,
    include_quality_evidence: bool = True,
) -> TextContent:
    """A hand-built, schema-valid ``TextContent`` toggling each optional OCR/Text layer on or off.

    Reuses the real ``build_quality_evidence`` builder so the resulting ``quality_evidence`` is
    always internally consistent (offsets/counts/lineage), rather than hand-satisfying every
    cross-field invariant in the test.
    """
    page = TextPageResult(
        page_number=1,
        source="pdf_text_layer",
        has_text_layer=True,
        ocr_used=False,
        text=raw_text,
        text_char_count=len(raw_text),
    )
    structured_content = _structured_content(raw_text) if include_structured else None

    reading: ReadingTextResult | None = None
    reading_text_map: list[ReadingTextMapSegment] = []
    if include_canonical:
        reading = ReadingTextResult(text=raw_text, status="heuristic", flags=())
        reading_text_map = [
            ReadingTextMapSegment(
                reading_start=0,
                reading_end=len(raw_text),
                raw_start=0,
                raw_end=len(raw_text),
                page_number=1,
                mapping_status="exact",
            )
        ]

    quality_evidence = None
    if include_quality_evidence:
        quality_evidence = build_quality_evidence(
            source="pdf_text_layer",
            text=raw_text,
            pages=[page],
            reading=reading,
            reading_text_map=reading_text_map,
            text_geometry=None,
            structured_content=structured_content,
        )

    return TextContent(
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ARTIFACT_ID,
        input_audit_artifact_id=_AUDIT_ARTIFACT_ID,
        source="pdf_text_layer",
        text=raw_text,
        text_char_count=len(raw_text),
        pages=[page],
        tool_versions={"pypdf": "test"},
        flags=[],
        reading_text_version=("1" if include_canonical else None),
        reading_text=(raw_text if include_canonical else None),
        reading_text_status=("heuristic" if include_canonical else None),
        reading_text_map_version=("1" if include_canonical else None),
        reading_text_map=reading_text_map,
        layout_text_result=(raw_text if include_layout else None),
        structured_content_version=("1" if include_structured else None),
        structured_content=structured_content,
        quality_evidence_version=("1" if include_quality_evidence else None),
        quality_evidence=quality_evidence,
    )


def _text_artifact(content: TextContent, *, artifact_id: str = _TEXT_ARTIFACT_ID) -> TextArtifact:
    return TextArtifact(
        id=artifact_id,
        document_id=content.document_id,
        input_artifact_id=content.input_artifact_id,
        input_audit_artifact_id=content.input_audit_artifact_id,
        created_at="2026-07-09T10:00:00.000000Z",
        content=content,
    )


def _full_package() -> DocumentTextPackageV1:
    return build_document_text_package(_text_artifact(_build_text_content()))


def _source(package: DocumentTextPackageV1, name: str) -> DocumentTextSourceV1:
    return next(source for source in package.text_sources if source.name == name)


def _text_sources(**overrides: DocumentTextSourceV1) -> list[DocumentTextSourceV1]:
    """A well-formed, fully-available five-source list for direct validator unit tests."""
    sources: dict[str, DocumentTextSourceV1] = {
        "technical_raw_text": DocumentTextSourceV1(
            name="technical_raw_text",
            role="authoritative_source_text",
            required=True,
            available=True,
            text=_RAW_TEXT,
            text_char_count=len(_RAW_TEXT),
        ),
        "canonical_reading_text": DocumentTextSourceV1(
            name="canonical_reading_text",
            role="human_readable_derived_text",
            required=False,
            available=True,
            text=_RAW_TEXT,
            text_char_count=len(_RAW_TEXT),
            status="heuristic",
        ),
        "layout_text": DocumentTextSourceV1(
            name="layout_text",
            role="visual_debug_text",
            required=False,
            available=True,
            text=_RAW_TEXT,
            text_char_count=len(_RAW_TEXT),
        ),
        "structured_content": DocumentTextSourceV1(
            name="structured_content",
            role="semantic_structure_hints",
            required=False,
            available=True,
        ),
        "quality_evidence": DocumentTextSourceV1(
            name="quality_evidence",
            role="trust_uncertainty_hints",
            required=False,
            available=True,
        ),
    }
    sources.update(overrides)
    return list(sources.values())


# --- 1. Builder tests ----------------------------------------------------------------------------


def test_builder_produces_contract_version_1_0() -> None:
    assert _full_package().contract_version == "1.0"


def test_builder_includes_document_id() -> None:
    assert _full_package().document_id == _DOCUMENT_ID


def test_builder_includes_expected_text_sources_and_roles() -> None:
    package = _full_package()
    roles_by_name = {source.name: source.role for source in package.text_sources}
    assert roles_by_name == {
        "technical_raw_text": "authoritative_source_text",
        "canonical_reading_text": "human_readable_derived_text",
        "layout_text": "visual_debug_text",
        "structured_content": "semantic_structure_hints",
        "quality_evidence": "trust_uncertainty_hints",
    }


def test_raw_text_role_is_authoritative_source_text() -> None:
    source = _source(_full_package(), "technical_raw_text")
    assert source.role == "authoritative_source_text"
    assert source.required is True


def test_canonical_role_is_human_readable_derived_text() -> None:
    source = _source(_full_package(), "canonical_reading_text")
    assert source.role == "human_readable_derived_text"
    assert source.required is False


def test_structured_content_role_is_semantic_structure_hints() -> None:
    assert _source(_full_package(), "structured_content").role == "semantic_structure_hints"


def test_quality_evidence_role_is_trust_uncertainty_hints() -> None:
    assert _source(_full_package(), "quality_evidence").role == "trust_uncertainty_hints"


def test_builder_output_is_deterministic() -> None:
    artifact = _text_artifact(_build_text_content())
    first = build_document_text_package(artifact)
    second = build_document_text_package(artifact)
    assert first == second
    assert first.model_dump() == second.model_dump()


def test_builder_does_not_mutate_source_artifact() -> None:
    artifact = _text_artifact(_build_text_content())
    before = artifact.model_dump()
    build_document_text_package(artifact)
    assert artifact.model_dump() == before


# --- 2. Validator / status tests -----------------------------------------------------------------


def test_full_artifact_is_valid() -> None:
    package = _full_package()
    assert package.contract_status == "valid"
    assert package.warnings == []
    assert package.blockers == []
    assert package.missing_capabilities == []


def test_missing_canonical_reading_text_is_degraded() -> None:
    content = _build_text_content(include_canonical=False)
    package = build_document_text_package(_text_artifact(content))
    assert package.contract_status == "degraded"
    assert "missing_canonical_reading_text" in package.warnings
    assert package.blockers == []


def test_missing_layout_text_is_degraded_not_invalid() -> None:
    content = _build_text_content(include_layout=False)
    package = build_document_text_package(_text_artifact(content))
    assert package.contract_status == "degraded"
    assert "missing_layout_text" in package.warnings
    assert package.blockers == []


def test_missing_structured_content_is_degraded_not_invalid() -> None:
    content = _build_text_content(include_structured=False)
    package = build_document_text_package(_text_artifact(content))
    assert package.contract_status == "degraded"
    assert "missing_structured_content" in package.warnings
    assert package.blockers == []


def test_missing_quality_evidence_is_degraded_not_invalid() -> None:
    content = _build_text_content(include_quality_evidence=False)
    package = build_document_text_package(_text_artifact(content))
    assert package.contract_status == "degraded"
    assert "missing_quality_evidence" in package.warnings
    assert "legacy_artifact" in package.warnings
    assert package.blockers == []


def test_partial_lineage_coverage_is_degraded() -> None:
    raw_text = "Hello world. Extra unmapped tail."
    page = TextPageResult(
        page_number=1,
        source="pdf_text_layer",
        has_text_layer=True,
        ocr_used=False,
        text=raw_text,
        text_char_count=len(raw_text),
    )
    # Only "Hello world." is mapped back to raw text; the rest of the reading text is unmapped.
    reading_text_map = [
        ReadingTextMapSegment(
            reading_start=0, reading_end=12, raw_start=0, raw_end=12, page_number=1,
            mapping_status="exact",
        )
    ]
    reading = ReadingTextResult(text=raw_text, status="heuristic", flags=())
    quality_evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=raw_text,
        pages=[page],
        reading=reading,
        reading_text_map=reading_text_map,
        text_geometry=None,
        structured_content=None,
    )
    assert quality_evidence.summary.lineage_summary.mapping_coverage_ratio < 1.0
    content = TextContent(
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ARTIFACT_ID,
        input_audit_artifact_id=_AUDIT_ARTIFACT_ID,
        source="pdf_text_layer",
        text=raw_text,
        text_char_count=len(raw_text),
        pages=[page],
        tool_versions={},
        flags=[],
        reading_text_version="1",
        reading_text=raw_text,
        reading_text_status="heuristic",
        reading_text_map_version="1",
        reading_text_map=reading_text_map,
        quality_evidence_version="1",
        quality_evidence=quality_evidence,
    )

    package = build_document_text_package(_text_artifact(content))

    assert package.contract_status == "degraded"
    assert "partial_lineage" in package.warnings
    assert package.blockers == []


def test_missing_raw_text_is_invalid() -> None:
    content = TextContent(
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ARTIFACT_ID,
        input_audit_artifact_id=_AUDIT_ARTIFACT_ID,
        source="docx_text",
        text="   ",
        text_char_count=3,
        pages=[],
        tool_versions={},
        flags=[],
    )

    package = build_document_text_package(_text_artifact(content))

    assert package.contract_status == "invalid"
    assert "missing_required_raw_text" in package.blockers
    assert package.warnings == []


def test_missing_document_id_is_invalid() -> None:
    evaluation = evaluate_contract_status(
        document_id="",
        contract_version="1.0",
        text_sources=_text_sources(),
        quality_evidence=None,
        reading_text_map=[],
    )

    assert evaluation.status == "invalid"
    assert "missing_document_id" in evaluation.blockers
    assert evaluation.warnings == []


def test_malformed_text_source_role_is_invalid() -> None:
    malformed_sources = _text_sources(
        canonical_reading_text=DocumentTextSourceV1(
            name="canonical_reading_text",
            role="visual_debug_text",  # wrong role for this source name
            required=False,
            available=True,
            text=_RAW_TEXT,
            text_char_count=len(_RAW_TEXT),
        )
    )

    evaluation = evaluate_contract_status(
        document_id=_DOCUMENT_ID,
        contract_version="1.0",
        text_sources=malformed_sources,
        quality_evidence=None,
        reading_text_map=[],
    )

    assert evaluation.status == "invalid"
    assert "invalid_text_source" in evaluation.blockers


def test_unsupported_contract_version_is_invalid() -> None:
    evaluation = evaluate_contract_status(
        document_id=_DOCUMENT_ID,
        contract_version="2.0",
        text_sources=_text_sources(),
        quality_evidence=None,
        reading_text_map=[],
    )

    assert evaluation.status == "invalid"
    assert "unsupported_contract_version" in evaluation.blockers


def test_missing_required_raw_text_source_is_invalid_via_validator() -> None:
    sources = _text_sources(
        technical_raw_text=DocumentTextSourceV1(
            name="technical_raw_text",
            role="authoritative_source_text",
            required=True,
            available=False,
            text="",
            text_char_count=0,
        )
    )

    evaluation = evaluate_contract_status(
        document_id=_DOCUMENT_ID,
        contract_version="1.0",
        text_sources=sources,
        quality_evidence=None,
        reading_text_map=[],
    )

    assert evaluation.status == "invalid"
    assert "missing_required_raw_text" in evaluation.blockers


# --- 3. Privacy tests ------------------------------------------------------------------------


def test_diagnostics_never_duplicate_raw_text_snippets() -> None:
    # A synthetic, IBAN-shaped marker — not a real account number — used only to prove it never
    # leaks into warning/blocker/summary metadata.
    sensitive_marker = "AT611904300234573201"
    content = _build_text_content(
        raw_text=f"Account {sensitive_marker} is due.",
        include_canonical=False,
        include_layout=False,
        include_structured=False,
        include_quality_evidence=False,
    )

    package = build_document_text_package(_text_artifact(content))

    assert package.contract_status == "degraded"
    diagnostics = json.dumps(
        {
            "warnings": package.warnings,
            "blockers": package.blockers,
            "missing_capabilities": package.missing_capabilities,
            "contract_validation_summary": package.contract_validation_summary.model_dump(),
        }
    )
    assert sensitive_marker not in diagnostics


def test_invalid_package_diagnostics_never_duplicate_raw_text_snippets() -> None:
    # A synthetic name — not a real person — embedded in an otherwise-available raw text source
    # whose package is still forced invalid (via an unresolvable document id), to prove the invalid
    # path never echoes source text into its diagnostic codes either.
    sensitive_marker = "Maria Musterfrau"
    sources = _text_sources(
        technical_raw_text=DocumentTextSourceV1(
            name="technical_raw_text",
            role="authoritative_source_text",
            required=True,
            available=True,
            text=f"Contact {sensitive_marker} for details.",
            text_char_count=len(f"Contact {sensitive_marker} for details."),
        )
    )

    evaluation = evaluate_contract_status(
        document_id="",
        contract_version="1.0",
        text_sources=sources,
        quality_evidence=None,
        reading_text_map=[],
    )

    assert evaluation.status == "invalid"
    diagnostics = json.dumps({"warnings": evaluation.warnings, "blockers": evaluation.blockers})
    assert sensitive_marker not in diagnostics


def test_validation_codes_are_stable_and_known() -> None:
    content = _build_text_content(include_canonical=False, include_quality_evidence=False)
    package = build_document_text_package(_text_artifact(content))

    assert package.warnings, "fixture must actually produce warnings to exercise this guard"
    for code in [*package.warnings, *package.blockers]:
        assert code in _KNOWN_WARNING_CODES


# --- 4. API tests ----------------------------------------------------------------------------


class _UnusedOcrAdapter:
    """Overrides the real OCR adapter dependency; a clean text-layer PDF must never call it."""

    def extract_result(self, image_path: Path) -> object:
        raise AssertionError("OCR adapter must not be invoked for a text-layer page")

    def tool_versions(self) -> dict[str, str]:
        return {"paddleocr": "unused"}


class _UnusedPdfRenderer:
    """Overrides the real PDF renderer dependency; a clean text-layer PDF must never call it."""

    def render_page(self, pdf_path: Path, page_number: int, output_dir: Path) -> Path:
        raise AssertionError("PDF renderer must not be invoked for a text-layer page")


@pytest.fixture
def _no_ocr_runtime(client: TestClient) -> Iterator[None]:
    app.dependency_overrides[provide_ocr_adapter] = lambda: _UnusedOcrAdapter()
    app.dependency_overrides[get_pdf_renderer] = lambda: _UnusedPdfRenderer()
    yield


@pytest.fixture(autouse=True)
def _allow_larger_uploads(settings: Settings) -> None:
    settings.max_upload_bytes = 2 * 1024 * 1024


_GOOD_TEXT = "The quick brown fox jumps over the lazy dog near the calm winding river today"


def _pdf_pages_bytes(*page_texts: str) -> bytes:
    writer = PdfWriter()
    for text in page_texts:
        page = writer.add_blank_page(width=200, height=200)
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
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _upload(client: TestClient, name: str, content: bytes, content_type: str) -> dict[str, object]:
    response = client.post("/api/uploads", files={"file": (name, content, content_type)})
    assert response.status_code == 201
    return response.json()


def _upload_and_audit(
    client: TestClient, name: str, content: bytes, content_type: str
) -> dict[str, object]:
    upload = _upload(client, name, content, content_type)
    response = client.post(f"/api/documents/{upload['id']}/audit")
    assert response.status_code == 201
    return upload


def _artifact_path(document_data_dir: Path, document_id: object, artifact_id: object) -> Path:
    return document_data_dir / str(document_id) / "artifacts" / f"{artifact_id}.json"


def test_text_package_endpoint_returns_package_for_document_with_ocr_artifact(
    client: TestClient, _no_ocr_runtime: None
) -> None:
    upload = _upload_and_audit(client, "text.pdf", _pdf_pages_bytes(_GOOD_TEXT), "application/pdf")
    created = client.post(f"/api/documents/{upload['id']}/ocr")
    assert created.status_code == 201

    response = client.get(f"/api/documents/{upload['id']}/text-package")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "1.0"
    assert body["document_id"] == upload["id"]
    assert body["text_artifact_id"] == created.json()["id"]
    assert body["contract_status"] in {"valid", "degraded"}
    assert body["blockers"] == []
    assert [source["name"] for source in body["text_sources"]] == [
        "technical_raw_text",
        "canonical_reading_text",
        "layout_text",
        "structured_content",
        "quality_evidence",
    ]


def test_text_package_endpoint_returns_404_when_no_ocr_artifact_exists(
    client: TestClient,
) -> None:
    upload = _upload_and_audit(client, "text.pdf", _pdf_pages_bytes(_GOOD_TEXT), "application/pdf")

    response = client.get(f"/api/documents/{upload['id']}/text-package")

    assert response.status_code == 404


def test_text_package_endpoint_returns_404_for_unknown_document(client: TestClient) -> None:
    response = client.get(f"/api/documents/{'0' * 32}/text-package")

    assert response.status_code == 404


def test_text_package_endpoint_degrades_gracefully_for_legacy_artifact(
    client: TestClient, document_data_dir: Path, _no_ocr_runtime: None
) -> None:
    upload = _upload_and_audit(client, "text.pdf", _pdf_pages_bytes(_GOOD_TEXT), "application/pdf")
    created = client.post(f"/api/documents/{upload['id']}/ocr").json()
    path = _artifact_path(document_data_dir, upload["id"], created["id"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    for field_name in (
        "readable_text",
        "reading_text_version",
        "reading_text",
        "reading_text_status",
        "reading_text_flags",
        "reading_text_map_version",
        "reading_text_map",
        "reading_text_geometry_projection_map_version",
        "reading_text_geometry_projection_map",
        "layout_text_result",
        "layout_blocks_version",
        "layout_blocks",
        "structured_content_version",
        "structured_content",
        "quality_evidence_version",
        "quality_evidence",
    ):
        payload["content"].pop(field_name, None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.get(f"/api/documents/{upload['id']}/text-package")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_status"] == "degraded"
    assert body["blockers"] == []
    assert "missing_canonical_reading_text" in body["warnings"]
    assert "missing_layout_text" in body["warnings"]
    assert "missing_structured_content" in body["warnings"]
    assert "missing_quality_evidence" in body["warnings"]
    assert "legacy_artifact" in body["warnings"]


def test_existing_ocr_endpoint_response_shape_is_unchanged(
    client: TestClient, _no_ocr_runtime: None
) -> None:
    upload = _upload_and_audit(client, "text.pdf", _pdf_pages_bytes(_GOOD_TEXT), "application/pdf")

    post_response = client.post(f"/api/documents/{upload['id']}/ocr")
    get_response = client.get(f"/api/documents/{upload['id']}/ocr")

    for response in (post_response, get_response):
        body = response.json()
        assert "contract_version" not in body
        assert "contract_status" not in body["content"]
        assert body["artifact_type"] == "text_result"
        assert body["station"] == "ocr"


def test_lineage_summary_reports_fallback_when_only_reading_text_map_exists() -> None:
    """A package with canonical text and the post-hoc map (but no geometry projection) names the
    fallback mechanism explicitly, so a consumer can tell the geometry-backed projection from the
    weaker unique-token string-match fallback. Neither is builder-emitted construction identity."""
    package = _full_package()
    assert package.lineage_summary is not None
    assert package.lineage_summary.canonical_available is True
    assert package.lineage_summary.geometry_projection_available is False
    assert package.lineage_summary.reading_text_map_available is True
    assert package.lineage_summary.lineage_source == "fallback_text_match"
    assert package.lineage_summary.geometry_projection_segment_count == 0


def test_lineage_summary_reports_unavailable_without_canonical_text() -> None:
    content = _build_text_content(include_canonical=False)
    package = build_document_text_package(_text_artifact(content))
    assert package.lineage_summary is not None
    assert package.lineage_summary.canonical_available is False
    assert package.lineage_summary.lineage_source == "unavailable"
