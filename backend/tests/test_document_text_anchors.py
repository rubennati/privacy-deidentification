"""Synthetic tests for Text Anchor Graph v1 (ADR-0031 Phase B).

The graph is a derived OCR/Text identity layer over ``DocumentTextPackageV1``. It must connect
technical raw, canonical reading, and layout ranges when lineage is explicit, and must mark missing
or ambiguous mapping without copying source text into anchor metadata.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from io import BytesIO
from typing import Literal, get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfWriter
from tests.artifact_helpers import save_text_artifact

from app.config import Settings
from app.schemas import (
    CanonicalTextSegmentV1,
    CanonicalTextSourceRange,
    DocumentTextAnchorGraphV1,
    DocumentTextAnchorV1,
    DocumentTextAnchorWarning,
    ReadingTextGeometryProjectionMap,
    ReadingTextGeometryProjectionSummary,
    ReadingTextMapSegment,
    TextArtifact,
    TextContent,
)
from app.services.document_text_anchors import build_document_text_anchor_graph
from app.services.document_text_package import build_document_text_package
from app.services.reading_text_projection import build_reading_text_map

_KNOWN_WARNING_CODES = frozenset(get_args(DocumentTextAnchorWarning))


def _hex_id(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()[:32]


_DOCUMENT_ID = _hex_id("anchor-document")
_ORIGINAL_ID = _hex_id("anchor-original")
_AUDIT_ID = _hex_id("anchor-audit")
_TEXT_ID = _hex_id("anchor-text")


def _segment(
    reading_start: int,
    reading_end: int,
    raw_start: int,
    raw_end: int,
    *,
    status: Literal["exact", "normalized", "partial"] = "exact",
) -> ReadingTextMapSegment:
    return ReadingTextMapSegment(
        reading_start=reading_start,
        reading_end=reading_end,
        raw_start=raw_start,
        raw_end=raw_end,
        mapping_status=status,
    )


def _content(
    raw: str,
    *,
    reading: str | None = None,
    reading_map: list[ReadingTextMapSegment] | None = None,
    layout: str | None = None,
) -> TextContent:
    return TextContent(
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ID,
        input_audit_artifact_id=_AUDIT_ID,
        source="docx_text",
        text=raw,
        text_char_count=len(raw),
        pages=[],
        tool_versions={"test": "1"},
        flags=[],
        reading_text_version=("1" if reading is not None else None),
        reading_text=reading,
        reading_text_status=("heuristic" if reading is not None else None),
        reading_text_map_version=("1" if reading is not None else None),
        reading_text_map=reading_map or [],
        layout_text_result=layout,
    )


def _artifact(content: TextContent, *, artifact_id: str = _TEXT_ID) -> TextArtifact:
    return TextArtifact(
        id=artifact_id,
        document_id=content.document_id,
        input_artifact_id=content.input_artifact_id,
        input_audit_artifact_id=content.input_audit_artifact_id,
        created_at="2026-07-09T10:00:00.000000Z",
        content=content,
    )


def _graph(content: TextContent) -> DocumentTextAnchorGraphV1:
    return build_document_text_anchor_graph(build_document_text_package(_artifact(content)))


def _anchors_with_status(
    graph: DocumentTextAnchorGraphV1, status: str
) -> list[DocumentTextAnchorV1]:
    return [anchor for anchor in graph.anchors if anchor.anchor_status == status]


# --- Builder basics ------------------------------------------------------------------------------


def test_builder_creates_raw_anchors_and_attaches_canonical_ranges() -> None:
    raw = "Alpha Beta"
    graph = _graph(
        _content(
            raw,
            reading=raw,
            reading_map=[_segment(0, len(raw), 0, len(raw))],
        )
    )

    assert graph.graph_version == "1.0"
    assert graph.document_id == _DOCUMENT_ID
    assert graph.summary.anchors_with_raw_range == 2
    assert graph.summary.anchors_with_canonical_range == 2
    assert graph.summary.raw_anchor_count == 2
    assert graph.summary.canonical_anchor_count == 2
    assert graph.summary.anchors_with_raw_and_canonical == 2
    assert graph.summary.anchors_with_raw_only == 0
    assert graph.summary.canonical_unmapped_count == 0
    assert graph.summary.raw_to_canonical_coverage_ratio == 1.0
    assert graph.validation.status == "degraded"  # layout is optional and absent in this fixture
    assert "missing_layout_text" in graph.warnings
    assert graph.validation.blockers == []
    assert all(
        {source_range.source_name for source_range in anchor.source_ranges}
        == {"technical_raw_text", "canonical_reading_text"}
        for anchor in graph.anchors
    )
    canonical_ranges = [
        (source_range.start, source_range.end)
        for anchor in graph.anchors
        for source_range in anchor.source_ranges
        if source_range.source_name == "canonical_reading_text"
    ]
    assert canonical_ranges == [(0, 5), (6, 10)]


def test_layout_missing_degrades_but_does_not_invalidate() -> None:
    graph = _graph(_content("Alpha", reading="Alpha", reading_map=[_segment(0, 5, 0, 5)]))

    assert graph.validation.status == "degraded"
    assert "missing_layout_text" in graph.warnings
    assert graph.validation.blockers == []


def test_canonical_missing_degrades_but_does_not_invalidate() -> None:
    graph = _graph(_content("Alpha", layout="Alpha"))

    assert graph.validation.status == "degraded"
    assert "missing_canonical_reading_text" in graph.warnings
    assert graph.validation.blockers == []
    assert graph.summary.single_source_count == 0  # raw + byte-aligned layout still connects
    assert graph.summary.exact_count == 1


def test_raw_missing_invalidates_graph() -> None:
    graph = _graph(_content("   ", layout=None))

    assert graph.validation.status == "invalid"
    assert graph.validation.blockers == ["missing_raw_text"]
    assert graph.summary.total_anchors == 0


# --- Mapping behavior ----------------------------------------------------------------------------


def test_partial_mapping_is_explicit_and_approximate() -> None:
    graph = _graph(
        _content(
            "SecretValue",
            reading="Secret",
            reading_map=[_segment(0, 6, 0, 6, status="partial")],
        )
    )

    anchor = graph.anchors[0]
    assert anchor.anchor_status == "partial"
    canonical_ranges = [
        source_range
        for source_range in anchor.source_ranges
        if source_range.source_name == "canonical_reading_text"
    ]
    assert len(canonical_ranges) == 1
    assert canonical_ranges[0].mapping_status == "partial"
    assert canonical_ranges[0].range_role == "approximate"
    assert graph.summary.partial_count == 1


def test_missing_mapping_stays_raw_reviewable_not_dropped() -> None:
    graph = _graph(
        _content(
            "Alpha Beta",
            reading="Alpha",
            reading_map=[_segment(0, 5, 0, 5)],
        )
    )

    missing = _anchors_with_status(graph, "missing")
    assert len(missing) == 1
    assert {source_range.source_name for source_range in missing[0].source_ranges} == {
        "technical_raw_text"
    }
    assert graph.summary.unmapped_raw_token_count == 1
    assert "unmapped_raw_tokens" in graph.warnings


def test_repeated_identical_words_are_not_globally_married() -> None:
    graph = _graph(_content("Anna Anna", reading="Anna Anna", reading_map=[]))
    raw_anchors = [
        anchor for anchor in graph.anchors if _has_source(anchor, "technical_raw_text")
    ]

    assert len(raw_anchors) == 2
    assert len({anchor.anchor_id for anchor in raw_anchors}) == 2
    assert all(anchor.anchor_status == "ambiguous" for anchor in raw_anchors)
    assert all(
        not _has_source(anchor, "canonical_reading_text") for anchor in raw_anchors
    )
    assert graph.summary.repeated_token_ambiguity_count == 2
    assert "ambiguous_repeated_token" in graph.warnings


def test_raw_only_token_stays_single_source_when_no_other_view_exists() -> None:
    graph = _graph(_content("Alpha"))

    assert graph.summary.total_anchors == 1
    assert graph.anchors[0].anchor_status == "single_source"
    assert graph.anchors[0].source_ranges[0].source_name == "technical_raw_text"


def test_canonical_only_token_is_represented_as_inserted_without_guessing() -> None:
    graph = _graph(
        _content("Alpha", reading="Alpha EXTRA", reading_map=[_segment(0, 5, 0, 5)])
    )

    inserted = _anchors_with_status(graph, "inserted")
    assert len(inserted) == 1
    assert inserted[0].source_ranges[0].source_name == "canonical_reading_text"
    assert graph.summary.unmapped_canonical_token_count == 1
    assert "unmapped_canonical_tokens" in graph.warnings


def test_byte_aligned_layout_ranges_are_attached_safely() -> None:
    raw = "Alpha Beta"
    graph = _graph(
        _content(
            raw,
            reading=raw,
            reading_map=[_segment(0, len(raw), 0, len(raw))],
            layout=raw,
        )
    )

    assert graph.validation.status == "valid"
    assert graph.summary.anchors_with_layout_range == graph.summary.anchors_with_raw_range
    assert graph.summary.layout_anchor_count == graph.summary.raw_anchor_count
    assert graph.summary.anchors_with_layout == graph.summary.anchors_with_layout_range
    assert graph.summary.layout_unmapped_count == 0
    assert graph.summary.raw_to_layout_coverage_ratio == 1.0


def test_non_aligned_layout_is_single_source_not_fuzzy_matched() -> None:
    graph = _graph(
        _content(
            "Alpha Beta",
            reading="Alpha Beta",
            reading_map=[_segment(0, 10, 0, 10)],
            layout="Beta Alpha",
        )
    )

    layout_only = [
        anchor
        for anchor in graph.anchors
        if _has_source(anchor, "layout_text")
        and not _has_source(anchor, "technical_raw_text")
    ]
    assert len(layout_only) == 2
    assert all(anchor.anchor_status == "single_source" for anchor in layout_only)
    assert "unsupported_source" in graph.warnings


# --- Line-boundary integrity (anchors are per-line identity units) -------------------------------


def test_no_anchor_raw_range_crosses_a_line_break() -> None:
    """A token pattern must never merge content from two lines into one anchor.

    A phone/number-shaped run that swallowed the ``\\n`` would fuse a line-ending date with the next
    line's leading number into a single bogus anchor, whose canonical range then spans unrelated
    reading text and whose PII binding degrades to ``partial`` — the exact cross-view highlight
    divergence this guards against.
    """
    raw = "Rechnung vom 15.03.2024\n1010 Wien\n"
    graph = _graph(_content(raw, reading=raw, reading_map=[_segment(0, len(raw), 0, len(raw))]))

    for anchor in graph.anchors:
        for source_range in anchor.source_ranges:
            if source_range.source_name == "technical_raw_text":
                assert "\n" not in raw[source_range.start : source_range.end], (
                    "anchor raw range must not span a line break"
                )


def test_line_ending_date_and_next_line_number_are_separate_anchors() -> None:
    raw = "vom 15.03.2024\n1010 Wien\n"
    graph = _graph(_content(raw))
    raw_tokens = {
        raw[source_range.start : source_range.end]
        for anchor in graph.anchors
        for source_range in anchor.source_ranges
        if source_range.source_name == "technical_raw_text"
    }

    assert "15.03.2024" in raw_tokens
    assert "1010" in raw_tokens
    assert not any("\n" in token for token in raw_tokens)


# --- Determinism and privacy ---------------------------------------------------------------------


def test_same_input_creates_same_anchor_ids_and_order() -> None:
    content = _content(
        "Alpha Beta",
        reading="Alpha Beta",
        reading_map=[_segment(0, 10, 0, 10)],
        layout="Alpha Beta",
    )

    first = _graph(content)
    second = _graph(content)

    assert [anchor.anchor_id for anchor in first.anchors] == [
        anchor.anchor_id for anchor in second.anchors
    ]
    assert first.model_dump() == second.model_dump()


def test_anchor_ids_do_not_depend_on_token_text_alone() -> None:
    graph = _graph(_content("Anna Anna", reading="Anna Anna", reading_map=[]))
    raw_ids = [
        anchor.anchor_id for anchor in graph.anchors if _has_source(anchor, "technical_raw_text")
    ]

    assert len(raw_ids) == len(set(raw_ids))


def test_anchor_metadata_does_not_copy_sensitive_source_text() -> None:
    marker = "secret.person@example.test"
    graph = _graph(
        _content(
            f"Contact {marker}",
            reading=f"Contact {marker}",
            reading_map=[_segment(0, len(f"Contact {marker}"), 0, len(f"Contact {marker}"))],
        )
    )

    metadata = json.dumps(
        {
            "anchors": [anchor.model_dump() for anchor in graph.anchors],
            "summary": graph.summary.model_dump(),
            "validation": graph.validation.model_dump(),
            "warnings": graph.warnings,
            "sources": [source.model_dump() for source in graph.sources],
        }
    )
    assert marker not in metadata
    assert "Contact" not in metadata
    assert any(anchor.token_class == "email_like" for anchor in graph.anchors)


def test_warning_codes_are_stable_and_known() -> None:
    graph = _graph(_content("Anna Anna", reading="Anna Anna", reading_map=[]))

    for code in [*graph.warnings, *graph.validation.blockers]:
        assert code in _KNOWN_WARNING_CODES


def test_schema_rejects_invalid_anchor_ranges() -> None:
    graph = _graph(_content("Alpha"))
    payload = graph.model_dump()
    payload["anchors"][0]["source_ranges"][0]["end"] = 99

    with pytest.raises(ValidationError):
        DocumentTextAnchorGraphV1.model_validate(payload)


# --- API behavior --------------------------------------------------------------------------------


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _upload_document(client: TestClient) -> str:
    response = client.post(
        "/api/uploads",
        files={"file": ("source.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _save_text(
    settings: Settings, document_id: str, *, raw: str, reading: str | None = None
) -> TextArtifact:
    content = TextContent(
        document_id=document_id,
        input_artifact_id=_hex_id(f"{document_id}-original"),
        input_audit_artifact_id=_hex_id(f"{document_id}-audit"),
        source="docx_text",
        text=raw,
        text_char_count=len(raw),
        pages=[],
        tool_versions={"test": "1"},
        flags=[],
        reading_text_version=("1" if reading is not None else None),
        reading_text=reading,
        reading_text_status=("heuristic" if reading is not None else None),
        reading_text_map_version=("1" if reading is not None else None),
        reading_text_map=(
            [_segment(0, len(reading), 0, len(raw))]
            if reading is not None and len(reading) == len(raw)
            else []
        ),
    )
    artifact = TextArtifact(
        id=_hex_id(f"{document_id}-text"),
        document_id=document_id,
        input_artifact_id=content.input_artifact_id,
        input_audit_artifact_id=content.input_audit_artifact_id,
        created_at="2026-07-09T10:00:00.000000Z",
        content=content,
    )
    save_text_artifact(settings, artifact)
    return artifact


def test_text_anchors_endpoint_returns_graph(client: TestClient, settings: Settings) -> None:
    document_id = _upload_document(client)
    marker = "anchor.person@example.test"
    artifact = _save_text(
        settings, document_id, raw=f"Contact {marker}", reading=f"Contact {marker}"
    )

    first = client.get(f"/api/documents/{document_id}/text-anchors")
    second = client.get(f"/api/documents/{document_id}/text-anchors")

    assert first.status_code == 200
    body = first.json()
    assert body["graph_version"] == "1.0"
    assert body["document_id"] == document_id
    assert body["text_artifact_id"] == artifact.id
    assert body["summary"]["total_anchors"] >= 2
    assert [anchor["anchor_id"] for anchor in body["anchors"]] == [
        anchor["anchor_id"] for anchor in second.json()["anchors"]
    ]
    assert marker not in json.dumps(body["anchors"])
    assert "Contact" not in json.dumps(body["anchors"])


def test_text_anchors_endpoint_returns_404_when_no_text_artifact_exists(
    client: TestClient,
) -> None:
    document_id = _upload_document(client)

    response = client.get(f"/api/documents/{document_id}/text-anchors")

    assert response.status_code == 404


def test_text_anchors_endpoint_returns_404_for_unknown_document(client: TestClient) -> None:
    response = client.get(f"/api/documents/{'0' * 32}/text-anchors")

    assert response.status_code == 404


def test_text_anchors_endpoint_degrades_gracefully_for_legacy_raw_only_artifact(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_text(settings, document_id, raw="Alpha Beta")

    response = client.get(f"/api/documents/{document_id}/text-anchors")

    assert response.status_code == 200
    body = response.json()
    assert body["validation"]["status"] == "degraded"
    assert body["validation"]["blockers"] == []
    assert "missing_canonical_reading_text" in body["warnings"]
    assert "missing_layout_text" in body["warnings"]
    assert body["summary"]["single_source_count"] == body["summary"]["total_anchors"]


@pytest.fixture(autouse=True)
def _allow_larger_uploads(settings: Settings) -> Iterator[None]:
    settings.max_upload_bytes = 2 * 1024 * 1024
    yield


def _has_source(anchor: DocumentTextAnchorV1, source_name: str) -> bool:
    return any(
        source_range.source_name == source_name for source_range in anchor.source_ranges
    )


# --- Geometry-backed reading projection preference (NOT construction-time lineage) ----------------
# The projection is a post-render mechanism: it re-derives canonical<->raw correspondence by
# searching the already-completed canonical text, exactly like the older post-hoc unique-token
# ``reading_text_map`` — the difference is granularity and a stricter global-uniqueness requirement,
# not a difference in when it runs. It is preferred when it resolves a line unambiguously; neither
# mechanism is builder-emitted construction identity.


def _projection_map(
    raw: str, reading: str, needles: list[str]
) -> ReadingTextGeometryProjectionMap:
    segments: list[CanonicalTextSegmentV1] = []
    for needle in sorted(needles, key=reading.index):
        cs = reading.index(needle)
        rs = raw.index(needle)
        segments.append(
            CanonicalTextSegmentV1(
                segment_id=_hex_id(f"{cs}-{cs + len(needle)}-{rs}-{rs + len(needle)}"),
                canonical_start=cs,
                canonical_end=cs + len(needle),
                source_range=CanonicalTextSourceRange(
                    start=rs, end=rs + len(needle), source_role="body"
                ),
                segment_role="body",
                mapping_status="exact",
                confidence=1.0,
                reason_codes=["geometry_line_projection"],
            )
        )
    mapped_chars = sum(segment.canonical_end - segment.canonical_start for segment in segments)
    return ReadingTextGeometryProjectionMap(
        segments=segments,
        summary=ReadingTextGeometryProjectionSummary(
            total_segments=len(segments),
            mapped_segments=len(segments),
            ambiguous_segments=0,
            inserted_segments=0,
            canonical_char_count=len(reading),
            mapped_canonical_char_count=mapped_chars,
            coverage_ratio=round(mapped_chars / len(reading), 6),
        ),
    )


def _projection_content(
    raw: str, reading: str, projection: ReadingTextGeometryProjectionMap | None
) -> TextContent:
    return TextContent(
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ID,
        input_audit_artifact_id=_AUDIT_ID,
        source="docx_text",
        text=raw,
        text_char_count=len(raw),
        pages=[],
        tool_versions={"test": "1"},
        flags=[],
        reading_text_version="1",
        reading_text=reading,
        reading_text_status="heuristic",
        reading_text_map_version="1",
        reading_text_map=build_reading_text_map(raw, reading, []),
        reading_text_geometry_projection_map_version="1" if projection is not None else None,
        reading_text_geometry_projection_map=projection,
    )


def test_graph_prefers_geometry_projection_and_reports_source() -> None:
    raw = "Alpha One\nBeta Two\n"
    reading = "Beta Two\nAlpha One\n"
    projection = _projection_map(raw, reading, ["Alpha One", "Beta Two"])
    graph = _graph(_projection_content(raw, reading, projection))

    assert graph.lineage_summary is not None
    assert graph.lineage_summary.lineage_source == "geometry_projection"
    assert graph.summary.canonical_geometry_projection_count > 0
    assert graph.summary.canonical_fallback_count == 0
    assert any("canonical_geometry_projection" in anchor.flags for anchor in graph.anchors)
    assert not any("canonical_map_lineage" in anchor.flags for anchor in graph.anchors)


def test_graph_falls_back_to_reading_text_map_when_no_geometry_projection() -> None:
    raw = "Alpha One\nBeta Two\n"
    reading = "Beta Two\nAlpha One\n"
    graph = _graph(_projection_content(raw, reading, None))

    assert graph.lineage_summary is not None
    assert graph.lineage_summary.lineage_source == "fallback_text_match"
    assert graph.summary.canonical_geometry_projection_count == 0
    assert any("canonical_map_lineage" in anchor.flags for anchor in graph.anchors)
