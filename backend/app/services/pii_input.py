"""PII intake adapter — consume the OCR Output Contract v1 Document Text Package (ADR-0028).

This module is the single bridge between the OCR/Text output boundary and PII detection. It turns a
:class:`DocumentTextPackageV1` (ADR-0027) into a stable, internal :class:`PiiInputDocumentV1` that
PII detection depends on, so the PII service no longer reaches into ``TextContent`` internals or the
OCR/PDF tools that produced them.

Contract rules PII follows here (ADR-0027 consumer rules):

- Technical raw text is the **primary** detection source (PII detects on raw exclusively today).
- Canonical reading text is a **contextual/secondary** source; layout text is presentation only.
- ``structured_content`` is a **hint** layer; quality/noise evidence is **trust/uncertainty**
  context. Neither silently suppresses an entity — they are attached as context, not applied.
- A **structurally invalid** package (unsupported version, malformed source roles, unresolvable
  document id) is rejected with a controlled error. A package that is invalid *only* because its raw
  text is empty is rejected: absence of trustworthy analyzed text is not a valid empty PII result.
  A **degraded** package (missing optional layers/lineage) is usable as
  long as raw text exists.

The adapter never mutates the package and never copies a raw text snippet into metadata: only the
text sources themselves carry text (they *are* the text layers), while hints/warnings are codes,
counts, and flags.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.errors import ApiError
from app.schemas import (
    DocumentTextPackageStatus,
    DocumentTextPackageV1,
    DocumentTextSourceV1,
    PiiInputSourceRole,
    ReadingTextMapSegment,
    StructuredSpan,
    TextArtifact,
)
from app.services.document_text_package import build_document_text_package

# Map each packaged source name to the PII-facing role it plays. Raw is the one primary detection
# source; canonical/layout are contextual; structure and quality/noise evidence are hint layers.
_ROLE_BY_SOURCE_NAME: dict[str, PiiInputSourceRole] = {
    "technical_raw_text": "primary",
    "canonical_reading_text": "contextual",
    "layout_text": "contextual",
    "structured_content": "structured_hint",
    "quality_evidence": "quality_hint",
}

# Blockers that make a package unusable for PII. Missing raw text is a trust failure, not a valid
# empty analysis. Kept in sync with the contract's blocker codes.
_STRUCTURAL_BLOCKERS = frozenset(
    {
        "missing_document_id",
        "unsupported_contract_version",
        "invalid_text_source",
        "missing_required_raw_text",
    }
)


class PiiInputContractError(ApiError):
    """Raised when a ``DocumentTextPackageV1`` is structurally invalid for PII detection."""

    def __init__(self) -> None:
        super().__init__("Document text package is not valid for PII detection.", 422)


@dataclass(frozen=True)
class PiiInputPage:
    """One page's exact detection text with its page number (``None`` for a non-paged document)."""

    page_number: int | None
    text: str


@dataclass(frozen=True)
class PiiInputTextSource:
    """One text layer with its PII-facing role. Mirrors a packaged ``DocumentTextSourceV1``."""

    name: str
    role: PiiInputSourceRole
    available: bool
    text: str | None = None
    char_count: int | None = None
    status: str | None = None
    flags: tuple[str, ...] = ()


# Structural kinds PII structural-context validation cares about. ``table_cell`` bounds a candidate
# to its cell, ``field_label``/``field_value`` a label/value pair, ``heading`` a section title.
PiiStructuralSpanKind = Literal["table_cell", "field_label", "field_value", "heading"]


@dataclass(frozen=True)
class PiiInputStructuralSpan:
    """One ``structured_content`` region exposed as offsets + role, never as text.

    This realizes the ``structured_hint`` role as *data* (not just an availability flag) so a later,
    strictly subtractive PII structural-context validation stage can clip or reject candidates. Both
    offset pairs index the **technical raw text PII detects on**, verified against the OCR builder,
    the schema validator, and PII's own per-page detection loop:

    - ``page_start``/``page_end`` are page-local into the raw per-page text (``PiiInputPage.text``),
      aligning with ``PiiEntity.page_start_offset``/``page_end_offset``.
    - ``raw_start``/``raw_end`` are global into the combined raw text (``primary_source.text``),
      aligning with ``PiiEntity.start_offset``/``end_offset``. Despite the ``StructuredSpan``
      schema's ``canonical_*`` naming, these offsets reference the raw text, not ``reading_text``.

    The global ``raw_*`` pair is the robust alignment key: a paged document also matches on
    ``page_number``, but a non-paged document (DOCX) carries structural ``page_number = 1`` while
    its detections carry ``page_number = None`` — only the raw offsets align there.

    ``role`` is a bounded code interpreted in the context of ``kind`` (the table cell role for
    ``table_cell``; the field type hint for ``field_label``/``field_value``; ``"section"`` for a
    heading). ``container_id`` is the owning table/field/section id. No source text is copied.
    """

    kind: PiiStructuralSpanKind
    page_number: int
    page_start: int
    page_end: int
    raw_start: int
    raw_end: int
    container_id: str
    role: str


@dataclass(frozen=True)
class PiiInputQualityHint:
    """Trust/uncertainty context from the package's quality evidence. Counts/flags only, no text."""

    overall_status: str
    overall_score: float | None
    has_noise_evidence: bool
    mapping_coverage_ratio: float
    warning_codes: tuple[str, ...]


@dataclass(frozen=True)
class PiiInputDocumentV1:
    """Stable internal PII input derived from one ``DocumentTextPackageV1``.

    Detection reads only from this model, never from ``TextContent``. ``pages`` preserves the exact
    per-page detection segmentation (so page-local offsets stay byte-identical to today); when
    empty, the caller detects on ``primary_source.text`` with a ``None`` page number.
    """

    document_id: str
    package_id: str
    contract_version: str
    contract_status: DocumentTextPackageStatus
    text_sources: tuple[PiiInputTextSource, ...]
    pages: tuple[PiiInputPage, ...]
    reading_text: str | None
    reading_text_map: tuple[ReadingTextMapSegment, ...]
    quality_hint: PiiInputQualityHint | None
    structural_spans: tuple[PiiInputStructuralSpan, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    missing_capabilities: tuple[str, ...] = ()

    @property
    def primary_source(self) -> PiiInputTextSource:
        """The one authoritative raw-text source PII detects on."""
        return next(source for source in self.text_sources if source.role == "primary")

    @property
    def secondary_sources(self) -> tuple[PiiInputTextSource, ...]:
        """Contextual (canonical/layout) sources — available to PII, not the detection input."""
        return tuple(source for source in self.text_sources if source.role == "contextual")

    @property
    def hint_sources(self) -> tuple[PiiInputTextSource, ...]:
        """Structured/quality hint sources — semantic/trust context, never applied to detection."""
        return tuple(
            source
            for source in self.text_sources
            if source.role in ("structured_hint", "quality_hint")
        )

    @property
    def has_usable_raw_text(self) -> bool:
        """True when the primary raw source has non-empty text to detect on."""
        return self.primary_source.available

    @property
    def has_structural_spans(self) -> bool:
        """True when ``structured_content`` exposed at least one usable structural region."""
        return bool(self.structural_spans)

    def source(self, name: str) -> PiiInputTextSource | None:
        return next((source for source in self.text_sources if source.name == name), None)

    def is_available(self, name: str) -> bool:
        source = self.source(name)
        return source is not None and source.available


def build_pii_input_document(
    package: DocumentTextPackageV1, *, pages: Sequence[PiiInputPage]
) -> PiiInputDocumentV1:
    """Adapt a ``DocumentTextPackageV1`` into the internal PII input, validating the contract.

    ``pages`` carries the per-page detection segmentation (the OCR Output Contract v1 exposes only
    the combined raw text, so segmentation is passed alongside it in v1). It is validated to
    reconstruct the packaged raw text exactly, so pages can never drift from the contract.
    """
    _reject_structurally_invalid(package)
    text_sources = tuple(_to_input_source(source) for source in package.text_sources)
    primary = _require_primary(text_sources)
    checked_pages = _validate_pages(primary, pages)
    return PiiInputDocumentV1(
        document_id=package.document_id,
        package_id=package.package_id,
        contract_version=package.contract_version,
        contract_status=package.contract_status,
        text_sources=text_sources,
        pages=checked_pages,
        reading_text=_canonical_text(text_sources),
        reading_text_map=tuple(package.reading_text_map),
        quality_hint=_build_quality_hint(package),
        structural_spans=_build_structural_spans(package),
        warnings=tuple(package.warnings),
        blockers=tuple(package.blockers),
        missing_capabilities=tuple(package.missing_capabilities),
    )


class PiiInputAdapter:
    """Convenience bridge from an OCR/Text artifact to the stable PII input contract.

    Concentrates the only coupling that remains: it builds the ``DocumentTextPackageV1`` from the
    artifact (the OCR Output Contract v1 boundary) and reads ``pages`` for per-page segmentation.
    Everything downstream depends on the returned :class:`PiiInputDocumentV1`, not on OCR internals.
    """

    @staticmethod
    def from_text_artifact(artifact: TextArtifact) -> PiiInputDocumentV1:
        package = build_document_text_package(artifact)
        pages = tuple(
            PiiInputPage(page_number=page.page_number, text=page.text)
            for page in artifact.content.pages
        )
        return build_pii_input_document(package, pages=pages)

    @staticmethod
    def from_package(
        package: DocumentTextPackageV1, *, pages: Sequence[PiiInputPage]
    ) -> PiiInputDocumentV1:
        return build_pii_input_document(package, pages=pages)


def _reject_structurally_invalid(package: DocumentTextPackageV1) -> None:
    if any(blocker in _STRUCTURAL_BLOCKERS for blocker in package.blockers):
        raise PiiInputContractError


def _to_input_source(source: DocumentTextSourceV1) -> PiiInputTextSource:
    role = _ROLE_BY_SOURCE_NAME.get(source.name)
    if role is None:  # An unknown source name is a malformed contract, not a silent pass-through.
        raise PiiInputContractError
    return PiiInputTextSource(
        name=source.name,
        role=role,
        available=source.available,
        text=source.text,
        char_count=source.text_char_count,
        status=source.status,
        flags=tuple(source.flags),
    )


def _require_primary(sources: tuple[PiiInputTextSource, ...]) -> PiiInputTextSource:
    primaries = [source for source in sources if source.role == "primary"]
    if len(primaries) != 1:
        raise PiiInputContractError
    return primaries[0]


def _validate_pages(
    primary: PiiInputTextSource, pages: Sequence[PiiInputPage]
) -> tuple[PiiInputPage, ...]:
    """Ensure per-page segmentation reconstructs the packaged raw text exactly (no drift)."""
    if not pages:
        return ()
    combined = "\n\n".join(page.text for page in pages)
    if combined != (primary.text or ""):
        raise PiiInputContractError
    return tuple(pages)


def _canonical_text(sources: tuple[PiiInputTextSource, ...]) -> str | None:
    canonical = next(
        (source for source in sources if source.name == "canonical_reading_text"), None
    )
    return canonical.text if canonical is not None else None


def _build_structural_spans(
    package: DocumentTextPackageV1,
) -> tuple[PiiInputStructuralSpan, ...]:
    """Flatten ``structured_content`` into offset-only structural spans (no source text).

    Emits one span per table cell, per field label and value, and per section heading. Table
    captions are skipped: the schema carries them as text without an offset span, and this stage is
    strictly offset-driven. The package is only read, never mutated.
    """
    structured = package.structured_content
    if structured is None:
        return ()
    spans: list[PiiInputStructuralSpan] = []
    for page in structured.pages:
        for table in page.tables:
            for cell in table.cells:
                spans.append(
                    _structural_span("table_cell", table.page_number, cell.span,
                                     container_id=table.table_id, role=cell.role)
                )
        for field in page.fields:
            spans.append(
                _structural_span("field_label", field.page_number, field.label_span,
                                 container_id=field.field_id, role=field.field_type_hint)
            )
            spans.append(
                _structural_span("field_value", field.page_number, field.value_span,
                                 container_id=field.field_id, role=field.field_type_hint)
            )
        for section in page.sections:
            spans.append(
                _structural_span("heading", section.page_number, section.heading_span,
                                 container_id=section.section_id, role="section")
            )
    return tuple(spans)


def _structural_span(
    kind: PiiStructuralSpanKind,
    page_number: int,
    span: StructuredSpan,
    *,
    container_id: str,
    role: str,
) -> PiiInputStructuralSpan:
    # ``StructuredSpan.canonical_*`` indexes the combined *raw* text (schema misnomer); expose it as
    # ``raw_*`` so consumers align on the raw coordinate system PII detects on.
    return PiiInputStructuralSpan(
        kind=kind,
        page_number=page_number,
        page_start=span.page_start,
        page_end=span.page_end,
        raw_start=span.canonical_start,
        raw_end=span.canonical_end,
        container_id=container_id,
        role=role,
    )


def _build_quality_hint(package: DocumentTextPackageV1) -> PiiInputQualityHint | None:
    evidence = package.quality_evidence
    if evidence is None:
        return None
    summary = evidence.summary
    has_noise = any(item.type == "ocr_noise_summary" for item in evidence.items)
    return PiiInputQualityHint(
        overall_status=summary.overall_status,
        overall_score=summary.overall_score,
        has_noise_evidence=has_noise,
        mapping_coverage_ratio=summary.lineage_summary.mapping_coverage_ratio,
        warning_codes=tuple(package.warnings),
    )
