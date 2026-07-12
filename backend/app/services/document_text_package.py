"""OCR Output Contract v1 — Document Text Package builder and validator (ADR-0027).

Packages one OCR/Text artifact's already-produced layers (technical raw text, canonical reading
text, layout text, structured content, and quality evidence) into a single, versioned,
consumer-facing contract with an explicit trust status. This is the stable boundary PII, Review,
pseudonymization, document analysis, export, and future local AI are meant to depend on instead of
reaching into ``TextContent`` internals or the OCR/PDF tools that produced them.

This module changes no OCR/Text behavior: it only reads an existing immutable ``TextArtifact`` and
deterministically derives a ``DocumentTextPackageV1`` from it, without mutating the source or any of
its fields. PII does not consume this contract yet — see
docs/adr/0027-ocr-output-contract-v1-strategy.md and docs/engine/ocr-layout-text-contract.md.

Two responsibilities are kept deliberately separate, mirroring the ADR's Builder/Validator split:

- :func:`build_document_text_package` (the builder) reads a real ``TextArtifact`` and assembles a
  fully schema-valid ``DocumentTextPackageV1``.
- :func:`evaluate_contract_status` (the validator) is a pure function over primitive identifiers and
  already-built sources, so every decision-table branch — including states a real ``TextArtifact``
  can never produce, like an unsupported ``contract_version`` — is directly testable without
  fighting the strict schema on the final package object.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.schemas import (
    DocumentTextPackageLineageSummary,
    DocumentTextPackageProcessingMetadata,
    DocumentTextPackageStatus,
    DocumentTextPackageV1,
    DocumentTextPackageValidationSummary,
    DocumentTextSourceV1,
    QualityEvidence,
    ReadingTextMapSegment,
    TextArtifact,
    TextContent,
)

_CONTRACT_VERSION = "1.0"
_DOCUMENT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

# The five packaged source roles, in the fixed order they are always emitted (ADR-0027). Keying the
# expected role by name lets the validator detect a malformed/mismatched pairing deterministically.
_EXPECTED_ROLE_BY_SOURCE_NAME = {
    "technical_raw_text": "authoritative_source_text",
    "canonical_reading_text": "human_readable_derived_text",
    "layout_text": "visual_debug_text",
    "structured_content": "semantic_structure_hints",
    "quality_evidence": "trust_uncertainty_hints",
}
_SOURCE_NAMES_IN_ORDER = tuple(_EXPECTED_ROLE_BY_SOURCE_NAME)
_REQUIRED_SOURCE_NAME = _SOURCE_NAMES_IN_ORDER[0]
_OPTIONAL_SOURCE_NAMES = _SOURCE_NAMES_IN_ORDER[1:]
_MISSING_WARNING_BY_SOURCE_NAME = {
    "canonical_reading_text": "missing_canonical_reading_text",
    "layout_text": "missing_layout_text",
    "structured_content": "missing_structured_content",
    "quality_evidence": "missing_quality_evidence",
}


@dataclass(frozen=True)
class ContractEvaluation:
    """The Document Text Package v1 validator's outcome: status plus stable diagnostic codes."""

    status: DocumentTextPackageStatus
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)


def build_document_text_package(artifact: TextArtifact) -> DocumentTextPackageV1:
    """Build the OCR Output Contract v1 package for one immutable OCR/Text artifact.

    Deterministic and read-only: every field is derived from ``artifact`` and the artifact itself is
    never mutated. ``package_id``/``text_artifact_id``/``created_at`` mirror the source artifact, so
    calling this twice with the same input always yields an equal package.
    """
    content = artifact.content
    text_sources = _build_text_sources(content)
    evaluation = evaluate_contract_status(
        document_id=artifact.document_id,
        contract_version=_CONTRACT_VERSION,
        text_sources=text_sources,
        quality_evidence=content.quality_evidence,
        reading_text_map=content.reading_text_map,
    )
    return DocumentTextPackageV1(
        contract_version=_CONTRACT_VERSION,
        package_id=artifact.id,
        document_id=artifact.document_id,
        text_artifact_id=artifact.id,
        created_at=artifact.created_at,
        contract_status=evaluation.status,
        warnings=list(evaluation.warnings),
        blockers=list(evaluation.blockers),
        missing_capabilities=list(evaluation.missing_capabilities),
        processing_metadata=_build_processing_metadata(content),
        text_sources=text_sources,
        structured_content=content.structured_content,
        quality_evidence=content.quality_evidence,
        reading_text_map=list(content.reading_text_map),
        reading_text_geometry_projection_map=content.reading_text_geometry_projection_map,
        reading_text_row_lineage_map=content.reading_text_row_lineage_map,
        lineage_summary=_build_lineage_summary(content, text_sources),
        contract_validation_summary=_build_validation_summary(evaluation, text_sources),
    )


def evaluate_contract_status(
    *,
    document_id: str,
    contract_version: str,
    text_sources: Sequence[DocumentTextSourceV1],
    quality_evidence: QualityEvidence | None,
    reading_text_map: Sequence[ReadingTextMapSegment],
) -> ContractEvaluation:
    """Deterministically compute ``valid``/``degraded``/``invalid`` plus stable diagnostic codes.

    ``invalid`` wins over ``degraded``: any blocker short-circuits with no warnings computed,
    since a consumer must refuse to treat an invalid package as usable at all. Absent required
    raw text, an unresolvable document id, an unsupported contract version, or a malformed source
    role/name pairing are all blockers; every other missing optional layer, incomplete lineage
    coverage, or a legacy (pre-quality-evidence) artifact is a warning that degrades, not
    invalidates, the package.
    Impossible offset ranges inside a text source are not re-checked here: the immutable
    ``TextArtifact``/``TextContent`` schema already forbids constructing one.
    """
    sources_by_name: dict[str, DocumentTextSourceV1] = {
        source.name: source for source in text_sources
    }
    blockers = _collect_contract_blockers(
        document_id=document_id,
        contract_version=contract_version,
        sources_by_name=sources_by_name,
    )
    if blockers:
        return ContractEvaluation(status="invalid", blockers=blockers)

    warnings, missing_capabilities = _collect_missing_source_warnings(sources_by_name)
    warnings.extend(_collect_quality_evidence_warnings(quality_evidence))
    warnings.extend(_collect_mapping_warnings(sources_by_name, reading_text_map))

    status: DocumentTextPackageStatus = "degraded" if warnings else "valid"
    return ContractEvaluation(
        status=status, warnings=warnings, missing_capabilities=missing_capabilities
    )


def _collect_contract_blockers(
    *,
    document_id: str,
    contract_version: str,
    sources_by_name: dict[str, DocumentTextSourceV1],
) -> list[str]:
    blockers: list[str] = []
    if not _DOCUMENT_ID_PATTERN.fullmatch(document_id):
        blockers.append("missing_document_id")
    if contract_version != _CONTRACT_VERSION:
        blockers.append("unsupported_contract_version")
    if _has_malformed_source(sources_by_name):
        blockers.append("invalid_text_source")

    raw_source = sources_by_name.get(_REQUIRED_SOURCE_NAME)
    if raw_source is None or not raw_source.available:
        blockers.append("missing_required_raw_text")
    return blockers


def _collect_missing_source_warnings(
    sources_by_name: dict[str, DocumentTextSourceV1],
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    missing_capabilities: list[str] = []
    for name in _OPTIONAL_SOURCE_NAMES:
        source = sources_by_name[name]
        if not source.available:
            warnings.append(_MISSING_WARNING_BY_SOURCE_NAME[name])
            missing_capabilities.append(name)
    return warnings, missing_capabilities


def _collect_quality_evidence_warnings(
    quality_evidence: QualityEvidence | None,
) -> list[str]:
    if quality_evidence is None:
        # No quality_evidence at all means this artifact predates OCR L14 — a coarser signal than
        # any single missing-layer warning, reported alongside "missing_quality_evidence" above.
        return ["legacy_artifact"]

    warnings: list[str] = []
    has_noise_summary = any(item.type == "ocr_noise_summary" for item in quality_evidence.items)
    if not has_noise_summary:
        warnings.append("missing_noise_evidence")

    coverage = quality_evidence.summary.lineage_summary.mapping_coverage_ratio
    if coverage < 1.0:
        warnings.append("partial_lineage")
    return warnings


def _collect_mapping_warnings(
    sources_by_name: dict[str, DocumentTextSourceV1],
    reading_text_map: Sequence[ReadingTextMapSegment],
) -> list[str]:
    canonical_available = sources_by_name["canonical_reading_text"].available
    if canonical_available and not reading_text_map:
        return ["missing_mapping"]
    return []


def _has_malformed_source(sources_by_name: dict[str, DocumentTextSourceV1]) -> bool:
    """True when a required source name is absent, or a present source's role does not match it."""
    for name, expected_role in _EXPECTED_ROLE_BY_SOURCE_NAME.items():
        source = sources_by_name.get(name)
        if source is None or source.name != name or source.role != expected_role:
            return True
    return False


def _build_text_sources(content: TextContent) -> list[DocumentTextSourceV1]:
    """Represent ``content``'s existing layers with explicit roles (ADR-0027 text sources).

    Raw text always carries its (possibly empty) string so ``available`` stays a pure semantic flag;
    the optional layers mirror their underlying field exactly (``None`` when absent). Structured
    content and quality evidence carry no ``text`` here — their full payload is exposed as its own
    typed field on :class:`DocumentTextPackageV1` instead of being duplicated per-source.
    """
    canonical_text = content.reading_text
    layout_text = content.layout_text_result
    structured_content = content.structured_content
    quality_evidence = content.quality_evidence
    canonical_available = canonical_text is not None
    layout_available = layout_text is not None
    structured_available = structured_content is not None
    evidence_available = quality_evidence is not None
    return [
        DocumentTextSourceV1(
            name="technical_raw_text",
            role="authoritative_source_text",
            required=True,
            available=bool(content.text.strip()),
            text=content.text,
            text_char_count=content.text_char_count,
        ),
        DocumentTextSourceV1(
            name="canonical_reading_text",
            role="human_readable_derived_text",
            required=False,
            available=canonical_available,
            text=canonical_text,
            text_char_count=(len(canonical_text) if canonical_text is not None else None),
            status=content.reading_text_status,
            flags=list(content.reading_text_flags),
        ),
        DocumentTextSourceV1(
            name="layout_text",
            role="visual_debug_text",
            required=False,
            available=layout_available,
            text=layout_text,
            text_char_count=(len(layout_text) if layout_text is not None else None),
        ),
        DocumentTextSourceV1(
            name="structured_content",
            role="semantic_structure_hints",
            required=False,
            available=structured_available,
            flags=(list(structured_content.flags) if structured_content is not None else []),
        ),
        DocumentTextSourceV1(
            name="quality_evidence",
            role="trust_uncertainty_hints",
            required=False,
            available=evidence_available,
        ),
    ]


def _build_processing_metadata(content: TextContent) -> DocumentTextPackageProcessingMetadata:
    return DocumentTextPackageProcessingMetadata(
        text_source=content.source,
        page_count=len(content.pages),
        ocr_used=any(page.ocr_used for page in content.pages),
        text_layer_used=any(page.has_text_layer for page in content.pages),
        tool_versions=dict(content.tool_versions),
    )


def _build_lineage_summary(
    content: TextContent, text_sources: Sequence[DocumentTextSourceV1]
) -> DocumentTextPackageLineageSummary:
    """Name the preferred raw↔canonical lineage mechanism available for this package.

    ``row_construction`` (builder-emitted, construction-time lineage — the authoritative identity
    source) is preferred over ``geometry_projection`` (a geometry-backed, post-render exact-line
    projection — an explicit post-hoc fallback, not construction identity), which is in turn
    preferred over the post-hoc unique-token ``reading_text_map`` (``fallback_text_match``);
    ``unavailable`` when there is no canonical text or no lineage at all. Preferring
    ``row_construction`` never guarantees it alone covers every span; anything a consumer resolves
    through the fallbacks is degraded mapping and stays per-anchor flagged as such. Text-free:
    booleans, counts, and coverage ratios only.
    """
    canonical_available = _canonical_source_available(text_sources)
    row_lineage_map = content.reading_text_row_lineage_map
    row_construction_available = row_lineage_map is not None
    projection_map = content.reading_text_geometry_projection_map
    projection_available = projection_map is not None
    reading_text_map_available = bool(content.reading_text_map)
    if row_construction_available:
        lineage_source = "row_construction"
    elif projection_available:
        lineage_source = "geometry_projection"
    elif reading_text_map_available:
        lineage_source = "fallback_text_match"
    else:
        lineage_source = "unavailable"
    return DocumentTextPackageLineageSummary(
        canonical_available=canonical_available,
        row_construction_available=row_construction_available,
        geometry_projection_available=projection_available,
        reading_text_map_available=reading_text_map_available,
        lineage_source=lineage_source,
        row_construction_segment_count=(
            row_lineage_map.summary.total_segments if row_lineage_map is not None else 0
        ),
        row_construction_coverage_ratio=(
            row_lineage_map.summary.coverage_ratio if row_lineage_map is not None else 0.0
        ),
        geometry_projection_segment_count=(
            projection_map.summary.mapped_segments if projection_map is not None else 0
        ),
        geometry_projection_ambiguous_count=(
            projection_map.summary.ambiguous_segments if projection_map is not None else 0
        ),
        reading_text_map_segment_count=len(content.reading_text_map),
        geometry_projection_coverage_ratio=(
            projection_map.summary.coverage_ratio if projection_map is not None else 0.0
        ),
    )


def _canonical_source_available(text_sources: Sequence[DocumentTextSourceV1]) -> bool:
    return any(
        source.name == "canonical_reading_text" and source.available for source in text_sources
    )


def _build_validation_summary(
    evaluation: ContractEvaluation, text_sources: Sequence[DocumentTextSourceV1]
) -> DocumentTextPackageValidationSummary:
    required_available = all(source.available for source in text_sources if source.required)
    available_count = sum(1 for source in text_sources if source.available)
    return DocumentTextPackageValidationSummary(
        contract_status=evaluation.status,
        warning_count=len(evaluation.warnings),
        blocker_count=len(evaluation.blockers),
        missing_capability_count=len(evaluation.missing_capabilities),
        required_sources_satisfied=required_available,
        available_source_count=available_count,
        total_source_count=len(text_sources),
    )
