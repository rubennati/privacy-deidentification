"""Candidate validation (Engine-5): a subtractive post-processing filter over already-detected
PII candidates.

This module never detects new PII. It only inspects candidates Presidio/spaCy already produced
and keeps, downgrades, or drops them. See ``docs/adr/0013-pii-candidate-validation.md`` and
``docs/engine/pii-engine-levels.md#candidate-validation-is-a-post-processing-exclusion-step``.

No raw candidate text is ever logged, returned, or stored: validation reasons are fixed,
machine-readable codes, and the per-run summary carries counts only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from app.services.pii_adapters import DetectedEntity
from app.services.pii_validation_rules import (
    has_address_line_context,
    has_company_suffix_context,
    has_contact_label_context,
    has_date_context,
    has_domain_label_context,
    has_financial_context,
    has_location_signal,
    has_name_context,
    has_name_shape,
    has_person_title_context,
    has_postal_code_context,
    is_function_word,
    is_generic_document_word,
    is_in_header_block,
    is_numeric_only,
    is_stopword,
    is_year_only,
    looks_like_a_date,
    tokenize,
)

Verdict = Literal["KEEP", "SCORE_DOWN", "DROP"]

# Entity types whose NER noise dominates broad-review/review-heavy false positives: full
# lexical/context validation.
STRONGLY_VALIDATED_TYPES: frozenset[str] = frozenset(
    {"PERSON", "ORGANIZATION", "LOCATION", "DATE_TIME"}
)
# Entity types validated only for obvious context/shape gaps; their recognizers are already
# pattern/context-strong, so the false-positive base rate is much lower to start with.
MODERATELY_VALIDATED_TYPES: frozenset[str] = frozenset(
    {
        "BIC", "OFFER_NUMBER", "CASE_NUMBER", "PROJECT_ID", "USER_ID", "FILE_REFERENCE",
        "REPORT_NUMBER", "ASSESSMENT_NUMBER", "CUSTOMER_NUMBER",
    }
)

# A SCORE_DOWN candidate is capped at this value: safely below the default 0.5 score threshold,
# so a downgraded candidate is excluded from the final layer unless a deployment has deliberately
# lowered PII_SCORE_THRESHOLD below this cap. See the ADR for the full rationale.
SCORE_DOWN_CAP = 0.3

_CONTEXT_WINDOW = 60


@dataclass(frozen=True)
class ValidationDecision:
    """One candidate's verdict. ``adjusted_score`` is only meaningful for ``SCORE_DOWN``."""

    verdict: Verdict
    reasons: tuple[str, ...]
    adjusted_score: float


@dataclass(frozen=True)
class ValidatedEntity:
    """A surviving candidate (``KEEP`` or a ``SCORE_DOWN`` that stayed above threshold)."""

    entity: DetectedEntity
    original_score: float
    validation_status: Literal["kept", "score_down"]
    validation_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ValidationSummary:
    """Aggregate, privacy-safe counts from one validation pass. No candidate text or context."""

    enabled: bool
    kept: int
    dropped: int
    score_down: int
    dropped_by_reason: dict[str, int]
    score_down_by_reason: dict[str, int]


def validate_candidate(
    entity_type: str,
    text: str,
    context_before: str,
    context_after: str,
    score: float,
    in_header_block: bool = False,
) -> ValidationDecision:
    """Decide KEEP/SCORE_DOWN/DROP for one already-detected candidate.

    Pure function: the candidate text/context are used only for in-memory comparisons and never
    appear in the returned decision. ``in_header_block`` marks a candidate that sits in the
    top-of-document header/address block (see ``is_in_header_block``), where a generic-word
    ORGANIZATION/LOCATION candidate is scored down rather than hard-dropped.
    """
    if entity_type in STRONGLY_VALIDATED_TYPES:
        return _validate_strong(
            entity_type, text, context_before, context_after, score, in_header_block
        )
    if entity_type == "BIC":
        return _validate_bic(context_before, context_after, score)
    if entity_type in MODERATELY_VALIDATED_TYPES:
        return _validate_moderate(entity_type, context_before, context_after, score)
    # "Light" types (structured + already context/pattern-gated domain identifiers): validation
    # runs for audit-trail uniformity but is a deliberate pass-through — see the ADR.
    return ValidationDecision("KEEP", (), score)


def _validate_strong(
    entity_type: str,
    text: str,
    context_before: str,
    context_after: str,
    score: float,
    in_header_block: bool,
) -> ValidationDecision:
    stripped = text.strip()
    if entity_type == "DATE_TIME":
        return _validate_date_time(stripped, context_before, context_after, score)

    if is_numeric_only(stripped):
        return ValidationDecision("DROP", ("NUMERIC_ONLY_FOR_NER",), score)
    if len(stripped) <= 2:
        return ValidationDecision("DROP", ("TOO_SHORT_SINGLE_TOKEN",), score)
    if is_stopword(stripped):
        return ValidationDecision("DROP", ("STOPWORD_ONLY",), score)
    if is_function_word(stripped):
        return ValidationDecision("DROP", ("FUNCTION_WORD_ONLY",), score)

    if entity_type == "PERSON":
        return _validate_person(stripped, context_before, context_after, score)
    if entity_type == "ORGANIZATION":
        return _validate_organization(
            stripped, context_before, context_after, score, in_header_block
        )
    return _validate_location(stripped, context_before, context_after, score, in_header_block)


def _validate_person(
    text: str, context_before: str, context_after: str, score: float
) -> ValidationDecision:
    if has_contact_label_context(context_before, context_after):
        return ValidationDecision("KEEP", ("CONTACT_PERSON_CONTEXT",), score)
    if has_person_title_context(context_before, context_after):
        return ValidationDecision("KEEP", ("PERSON_TITLE_CONTEXT",), score)
    if has_name_context(context_before, context_after) or has_name_shape(text):
        return ValidationDecision("KEEP", (), score)
    tokens = tokenize(text)
    if len(tokens) == 1 and tokens[0].islower():
        return ValidationDecision("DROP", ("NER_SINGLE_COMMON_WORD",), score)
    return ValidationDecision(
        "SCORE_DOWN", ("MISSING_REQUIRED_CONTEXT",), min(score, SCORE_DOWN_CAP)
    )


def _validate_organization(
    text: str, context_before: str, context_after: str, score: float, in_header_block: bool
) -> ValidationDecision:
    if has_company_suffix_context(text, context_before, context_after):
        return ValidationDecision("KEEP", ("COMPANY_SUFFIX_CONTEXT",), score)
    if is_generic_document_word(text):
        if in_header_block:
            return ValidationDecision(
                "SCORE_DOWN", ("HEADER_BLOCK_CONTEXT",), min(score, SCORE_DOWN_CAP)
            )
        return ValidationDecision("DROP", ("GENERIC_DOCUMENT_WORD",), score)
    return ValidationDecision(
        "SCORE_DOWN", ("ORG_WITHOUT_ORG_SIGNAL",), min(score, SCORE_DOWN_CAP)
    )


def _validate_location(
    text: str, context_before: str, context_after: str, score: float, in_header_block: bool
) -> ValidationDecision:
    if has_location_signal(text, context_before, context_after):
        return ValidationDecision("KEEP", (), score)
    if is_generic_document_word(text):
        if in_header_block:
            return ValidationDecision(
                "SCORE_DOWN", ("HEADER_BLOCK_CONTEXT",), min(score, SCORE_DOWN_CAP)
            )
        return ValidationDecision("DROP", ("GENERIC_DOCUMENT_WORD",), score)
    return ValidationDecision(
        "SCORE_DOWN", ("LOCATION_WITHOUT_LOCATION_SIGNAL",), min(score, SCORE_DOWN_CAP)
    )


def _validate_date_time(
    text: str, context_before: str, context_after: str, score: float
) -> ValidationDecision:
    if has_address_line_context(text, context_before, context_after):
        return ValidationDecision(
            "SCORE_DOWN", ("ADDRESS_LINE_NUMERIC_CONTEXT",), min(score, SCORE_DOWN_CAP)
        )
    if is_year_only(text):
        if has_postal_code_context(text, context_before, context_after):
            return ValidationDecision(
                "SCORE_DOWN", ("POSTAL_CODE_CONTEXT",), min(score, SCORE_DOWN_CAP)
            )
        if has_date_context(context_before, context_after):
            return ValidationDecision("KEEP", (), score)
        return ValidationDecision("SCORE_DOWN", ("DATE_YEAR_ONLY",), min(score, SCORE_DOWN_CAP))
    if looks_like_a_date(text):
        return ValidationDecision("KEEP", (), score)
    return ValidationDecision(
        "SCORE_DOWN", ("LOW_SHAPE_CONFIDENCE",), min(score, SCORE_DOWN_CAP)
    )


def _validate_bic(context_before: str, context_after: str, score: float) -> ValidationDecision:
    if has_financial_context(context_before, context_after):
        return ValidationDecision("KEEP", (), score)
    return ValidationDecision(
        "SCORE_DOWN", ("BIC_WITHOUT_FINANCIAL_CONTEXT",), min(score, SCORE_DOWN_CAP)
    )


def _validate_moderate(
    entity_type: str, context_before: str, context_after: str, score: float
) -> ValidationDecision:
    if has_domain_label_context(entity_type, context_before, context_after):
        return ValidationDecision("KEEP", (), score)
    return ValidationDecision(
        "SCORE_DOWN", ("MISSING_REQUIRED_CONTEXT",), min(score, SCORE_DOWN_CAP)
    )


def validate_candidates(
    candidates: Sequence[tuple[DetectedEntity, int, int | None]],
    page_texts: Mapping[int | None, str],
    score_threshold: float,
    enabled: bool,
) -> tuple[list[tuple[ValidatedEntity, int, int | None]], ValidationSummary]:
    """Apply candidate validation to every ``(entity, global_base, page_number)`` tuple.

    ``page_texts`` maps each page number (``None`` for a non-paged document) to the exact text
    the analyzer was given for that page/document, so a small context window can be sliced
    locally. A ``SCORE_DOWN`` candidate whose capped score falls below ``score_threshold`` is
    excluded from the returned list (the existing threshold is the single gate for the final
    layer) but is still counted under ``score_down`` in the summary, distinct from ``dropped``.
    Context text is used only for in-process comparisons; it is never stored or returned.
    """
    kept = 0
    dropped = 0
    score_down = 0
    dropped_by_reason: dict[str, int] = {}
    score_down_by_reason: dict[str, int] = {}
    output: list[tuple[ValidatedEntity, int, int | None]] = []

    for entity, global_base, page_number in candidates:
        if not enabled:
            output.append(
                (ValidatedEntity(entity, entity.score, "kept", ()), global_base, page_number)
            )
            kept += 1
            continue

        local_text = page_texts.get(page_number, "")
        candidate_text = local_text[entity.start : entity.end]
        context_before = local_text[max(0, entity.start - _CONTEXT_WINDOW) : entity.start]
        context_after = local_text[entity.end : entity.end + _CONTEXT_WINDOW]

        decision = validate_candidate(
            entity.entity_type,
            candidate_text,
            context_before,
            context_after,
            entity.score,
            is_in_header_block(local_text, entity.start),
        )

        if decision.verdict == "DROP":
            dropped += 1
            for reason in decision.reasons:
                dropped_by_reason[reason] = dropped_by_reason.get(reason, 0) + 1
            continue

        if decision.verdict == "SCORE_DOWN":
            score_down += 1
            for reason in decision.reasons:
                score_down_by_reason[reason] = score_down_by_reason.get(reason, 0) + 1
            if decision.adjusted_score < score_threshold:
                continue
            validated = ValidatedEntity(
                replace(entity, score=decision.adjusted_score),
                entity.score,
                "score_down",
                decision.reasons,
            )
        else:
            validated = ValidatedEntity(entity, entity.score, "kept", ())

        output.append((validated, global_base, page_number))
        kept += 1

    return output, ValidationSummary(
        enabled=enabled,
        kept=kept,
        dropped=dropped,
        score_down=score_down,
        dropped_by_reason=dict(sorted(dropped_by_reason.items())),
        score_down_by_reason=dict(sorted(score_down_by_reason.items())),
    )
