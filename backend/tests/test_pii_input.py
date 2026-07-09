"""Unit tests for the PII intake adapter (ADR-0028).

All data is synthetic. The adapter turns a DocumentTextPackageV1 (built from a hand-made
TextArtifact) into a stable PiiInputDocumentV1, so PII depends on the OCR Output Contract v1
boundary rather than on TextContent internals. No private corpus, no OCR runtime, no raw document
text in any metadata assertion.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from app.schemas import (
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
from app.services.document_text_package import build_document_text_package
from app.services.ocr_quality import build_quality_evidence
from app.services.pii_input import (
    PiiInputAdapter,
    PiiInputContractError,
    PiiInputPage,
    build_pii_input_document,
)
from app.services.reading_text import ReadingTextResult


def _hex_id(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()[:32]


_DOCUMENT_ID = _hex_id("document")
_ORIGINAL_ID = _hex_id("original")
_AUDIT_ID = _hex_id("audit")
_TEXT_ID = _hex_id("text")
_RAW = "Hello world."


def _structured_content(raw: str) -> StructuredContent:
    label = raw.split(" ", 1)[0]
    label_end = len(label)
    value = raw[label_end + 1 :].split(".", 1)[0]
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
    return StructuredContent(
        pages=[StructuredPageContent(page_number=1, fields=[field], source="canonical_text",
                                     confidence=0.9)],
        summary=StructuredContentSummary(page_count=1, table_count=0, field_count=1,
                                         section_count=0),
        flags=["span_backed"],
    )


def _text_artifact(
    *,
    raw: str = _RAW,
    include_canonical: bool = True,
    include_layout: bool = True,
    include_structured: bool = True,
    include_quality: bool = True,
) -> TextArtifact:
    page = TextPageResult(
        page_number=1,
        source="pdf_text_layer",
        has_text_layer=True,
        ocr_used=False,
        text=raw,
        text_char_count=len(raw),
    )
    structured = _structured_content(raw) if include_structured else None
    reading: ReadingTextResult | None = None
    reading_map: list[ReadingTextMapSegment] = []
    if include_canonical:
        reading = ReadingTextResult(text=raw, status="heuristic", flags=())
        reading_map = [
            ReadingTextMapSegment(
                reading_start=0, reading_end=len(raw), raw_start=0, raw_end=len(raw),
                page_number=1, mapping_status="exact",
            )
        ]
    quality = None
    if include_quality:
        quality = build_quality_evidence(
            source="pdf_text_layer",
            text=raw,
            pages=[page],
            reading=reading,
            reading_text_map=reading_map,
            text_geometry=None,
            structured_content=structured,
        )
    content = TextContent(
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ID,
        input_audit_artifact_id=_AUDIT_ID,
        source="pdf_text_layer",
        text=raw,
        text_char_count=len(raw),
        pages=[page],
        tool_versions={"pypdf": "test"},
        flags=[],
        reading_text_version=("1" if include_canonical else None),
        reading_text=(raw if include_canonical else None),
        reading_text_status=("heuristic" if include_canonical else None),
        reading_text_map_version=("1" if include_canonical else None),
        reading_text_map=reading_map,
        layout_text_result=(raw if include_layout else None),
        structured_content_version=("1" if include_structured else None),
        structured_content=structured,
        quality_evidence_version=("1" if include_quality else None),
        quality_evidence=quality,
    )
    return TextArtifact(
        id=_TEXT_ID,
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ID,
        input_audit_artifact_id=_AUDIT_ID,
        created_at="2026-07-09T10:00:00.000000Z",
        content=content,
    )


def _pages(artifact: TextArtifact) -> list[PiiInputPage]:
    return [PiiInputPage(page_number=p.page_number, text=p.text) for p in artifact.content.pages]


# --- 1. Adapter builds the internal input from a full package ------------------------------------


def test_builds_input_from_full_package() -> None:
    pii_input = PiiInputAdapter.from_text_artifact(_text_artifact())
    assert pii_input.document_id == _DOCUMENT_ID
    assert pii_input.package_id == _TEXT_ID
    assert pii_input.contract_version == "1.0"
    assert pii_input.contract_status == "valid"
    assert {source.name for source in pii_input.text_sources} == {
        "technical_raw_text",
        "canonical_reading_text",
        "layout_text",
        "structured_content",
        "quality_evidence",
    }


def test_raw_source_is_primary_and_is_the_detection_text() -> None:
    pii_input = PiiInputAdapter.from_text_artifact(_text_artifact())
    assert pii_input.primary_source.name == "technical_raw_text"
    assert pii_input.primary_source.role == "primary"
    assert pii_input.primary_source.text == _RAW
    assert pii_input.has_usable_raw_text is True


def test_canonical_source_is_contextual_not_primary() -> None:
    pii_input = PiiInputAdapter.from_text_artifact(_text_artifact())
    canonical = pii_input.source("canonical_reading_text")
    assert canonical is not None
    assert canonical.role == "contextual"
    assert canonical in pii_input.secondary_sources
    assert canonical not in (pii_input.primary_source,)
    assert pii_input.reading_text == _RAW


def test_structured_content_is_a_hint_layer() -> None:
    pii_input = PiiInputAdapter.from_text_artifact(_text_artifact())
    structured = pii_input.source("structured_content")
    assert structured is not None
    assert structured.role == "structured_hint"
    assert structured in pii_input.hint_sources
    assert structured.available is True


def test_quality_evidence_is_a_trust_hint_layer() -> None:
    pii_input = PiiInputAdapter.from_text_artifact(_text_artifact())
    assert pii_input.is_available("quality_evidence") is True
    assert pii_input.quality_hint is not None
    assert pii_input.quality_hint.mapping_coverage_ratio == pytest.approx(1.0)
    assert pii_input.quality_hint.has_noise_evidence is True


# --- 2. Contract status handling -----------------------------------------------------------------


def test_valid_package_is_accepted() -> None:
    pii_input = PiiInputAdapter.from_text_artifact(_text_artifact())
    assert pii_input.contract_status == "valid"
    assert pii_input.has_usable_raw_text is True


def test_degraded_package_with_raw_text_is_accepted() -> None:
    artifact = _text_artifact(include_canonical=False, include_quality=False)
    pii_input = PiiInputAdapter.from_text_artifact(artifact)
    assert pii_input.contract_status == "degraded"
    assert pii_input.has_usable_raw_text is True
    assert pii_input.reading_text is None
    assert pii_input.quality_hint is None
    assert "missing_canonical_reading_text" in pii_input.warnings


def test_optional_missing_layers_do_not_crash() -> None:
    artifact = _text_artifact(
        include_canonical=False,
        include_layout=False,
        include_structured=False,
        include_quality=False,
    )
    pii_input = PiiInputAdapter.from_text_artifact(artifact)
    assert pii_input.contract_status == "degraded"
    assert pii_input.has_usable_raw_text is True
    assert pii_input.is_available("layout_text") is False
    assert pii_input.is_available("structured_content") is False


def test_empty_raw_text_is_not_a_hard_error_but_has_no_usable_text() -> None:
    content = TextContent(
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ID,
        input_audit_artifact_id=_AUDIT_ID,
        source="docx_text",
        text="   ",
        text_char_count=3,
        pages=[],
        tool_versions={},
        flags=[],
    )
    artifact = TextArtifact(
        id=_TEXT_ID,
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ID,
        input_audit_artifact_id=_AUDIT_ID,
        created_at="2026-07-09T10:00:00.000000Z",
        content=content,
    )

    pii_input = PiiInputAdapter.from_text_artifact(artifact)

    assert pii_input.contract_status == "invalid"
    assert pii_input.has_usable_raw_text is False


def test_structurally_invalid_package_is_rejected() -> None:
    package = build_document_text_package(_text_artifact())
    # Force a structural blocker (a malformed source role would produce this on a real artifact);
    # model_copy does not re-validate, mirroring a package that failed structural validation.
    invalid = package.model_copy(
        update={"contract_status": "invalid", "warnings": [], "blockers": ["invalid_text_source"]}
    )

    with pytest.raises(PiiInputContractError):
        build_pii_input_document(invalid, pages=[])


def test_unsupported_version_blocker_is_rejected() -> None:
    package = build_document_text_package(_text_artifact())
    invalid = package.model_copy(
        update={
            "contract_status": "invalid",
            "warnings": [],
            "blockers": ["unsupported_contract_version"],
        }
    )

    with pytest.raises(PiiInputContractError):
        build_pii_input_document(invalid, pages=[])


def test_page_segmentation_must_reconstruct_raw_text() -> None:
    package = build_document_text_package(_text_artifact())

    with pytest.raises(PiiInputContractError):
        build_pii_input_document(package, pages=[PiiInputPage(page_number=1, text="mismatch")])


def test_matching_pages_are_preserved() -> None:
    artifact = _text_artifact()
    pii_input = build_pii_input_document(
        build_document_text_package(artifact), pages=_pages(artifact)
    )
    assert [page.text for page in pii_input.pages] == [_RAW]
    assert [page.page_number for page in pii_input.pages] == [1]


# --- 3. Immutability + privacy -------------------------------------------------------------------


def test_source_package_is_not_mutated() -> None:
    package = build_document_text_package(_text_artifact())
    before = package.model_dump()
    build_pii_input_document(package, pages=[PiiInputPage(page_number=1, text=_RAW)])
    assert package.model_dump() == before


def test_no_raw_snippets_duplicated_into_metadata() -> None:
    # A synthetic IBAN-shaped marker inside raw text; it must never leak into hint/warning metadata.
    marker = "AT611904300234573201"
    raw = f"Account {marker} is due."
    artifact = _text_artifact(raw=raw, include_canonical=False, include_quality=False)
    pii_input = build_pii_input_document(
        build_document_text_package(artifact), pages=_pages(artifact)
    )

    metadata = json.dumps(
        {
            "warnings": list(pii_input.warnings),
            "blockers": list(pii_input.blockers),
            "missing_capabilities": list(pii_input.missing_capabilities),
        }
    )
    assert marker not in metadata
    # The marker is allowed only in the raw text source itself (that source *is* the text layer).
    assert pii_input.primary_source.text is not None and marker in pii_input.primary_source.text
    for source in pii_input.text_sources:
        if source.name not in ("technical_raw_text", "layout_text"):
            assert source.text is None
