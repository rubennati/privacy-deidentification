"""Unified stable Review Result entries (Review Result v1).

Builds one coherent :class:`PiiReviewResultEntry` per detected occurrence and manual addition, on
top of the existing decision overlay (``pii_review_service.py``) and the anchor-bound entity
identity machinery (``pii_anchor_binding.py`` / ``pii_entity_display.py``). This is the flat,
single-shape view a downstream Replacement Plan can consume without distinguishing detector-origin
occurrences from reviewer-added manual additions, or reading the review overlay's own JSONL/decision
internals.

Identity stays occurrence/addition-id primary (ADR-0033/ADR-0034's guardrail): ``entry_id`` is
never anchor-derived. ``anchor_entity_id`` is an additive, freshly-recomputed secondary reference,
built by rebinding the *exact* pii/text artifact pair an entry actually originated from — never
"today's" pair for a stale entry — so a re-run, tokenizer change, or newer anchor-graph builder
version can never silently reattach an old decision to a different entity. Missing/ambiguous anchor
identity is an explicit ``unresolved`` state; a structurally broken reference (stored offsets that
no longer fit their own referenced text) is an explicit ``incompatible`` state — neither is ever
silently dropped or guessed. Manual additions are never run through anchor binding here (ADR-0035's
explicit non-goal: they stay out of ``pii_result``/the anchor-bound entity contract); their
identity/mapping quality reuses the reverse canonical-to-raw projection already resolved once at
add time (``pii_manual_addition.py``), never re-guessed.

This module never mutates ``pii_result``, text artifacts, or the anchor graph; it only reads them.
"""

from __future__ import annotations

from app.schemas import (
    AnchorBoundPiiEntityV1,
    DocumentTextAnchorGraphV1,
    PiiEntity,
    PiiEntityMappingStatus,
    PiiEntityReviewReasonCode,
    PiiManualAddition,
    PiiReviewOccurrence,
    PiiReviewResultEntry,
    TextArtifact,
)
from app.services.document_text_anchors import build_document_text_anchor_graph
from app.services.document_text_package import build_document_text_package
from app.services.pii_anchor_binding import bind_pii_entities_to_anchors
from app.services.pii_entity_display import (
    anchor_display_range,
    classify_mapping_status,
    identity_reason_codes,
)

_RAW_PROJECTION_TO_MAPPING: dict[str, PiiEntityMappingStatus] = {
    "exact": "exact",
    "partial": "partial",
    "unmapped": "missing",
}


def build_detected_entries(
    *,
    document_id: str,
    pii_artifact_id: str,
    text_artifact_id: str,
    text_artifact: TextArtifact | None,
    entities: list[PiiEntity],
    occurrences: list[PiiReviewOccurrence],
    is_current: bool,
) -> list[PiiReviewResultEntry]:
    """Build one entry per detected occurrence, rebinding against the artifact pair it belongs to.

    ``text_artifact`` must be the exact text artifact this ``pii_artifact_id`` ran against (the
    caller resolves that pairing) — never a different/"current" text artifact, so identity is never
    computed against unrelated text. A missing/unbuildable anchor graph degrades every entity to the
    same graceful evidence-only (``unresolved``) state ``pii_anchor_binding.py`` already uses; it is
    never treated as a structural break.
    """
    canonical_available = text_artifact is not None and bool(text_artifact.content.reading_text)
    reading_text = text_artifact.content.reading_text if text_artifact is not None else None
    graph = _anchor_graph(text_artifact)
    bound_entities, _summary = bind_pii_entities_to_anchors(
        entities, graph, document_id=document_id
    )
    bound_by_occurrence: dict[str, AnchorBoundPiiEntityV1] = {
        detection_id: bound
        for bound in bound_entities
        for detection_id in (obs.detection_id for obs in bound.source_observations)
    }
    entity_by_id = {entity.id: entity for entity in entities}
    currency = "current" if is_current else "stale"

    entries: list[PiiReviewResultEntry] = []
    for occurrence in occurrences:
        entity = entity_by_id[occurrence.occurrence_id]
        bound = bound_by_occurrence[occurrence.occurrence_id]

        anchor_canonical = anchor_display_range(bound, "canonical_reading_text")
        anchor_canonical_range = anchor_canonical[0] if anchor_canonical is not None else None
        anchor_canonical_exact = anchor_canonical[1] if anchor_canonical is not None else True
        mapping_status = classify_mapping_status(
            entity,
            canonical_available,
            reading_text,
            anchor_canonical_range=anchor_canonical_range,
            anchor_canonical_exact=anchor_canonical_exact,
        )
        identity_status, reason_codes, anchor_entity_id = _detected_identity(bound, mapping_status)

        entries.append(
            PiiReviewResultEntry(
                entry_id=occurrence.occurrence_id,
                origin="detected",
                entity_type=occurrence.entity_type,
                entity_group_id=occurrence.entity_group_id,
                pii_artifact_id=pii_artifact_id,
                text_artifact_id=text_artifact_id,
                artifact_currency=currency,
                identity_status=identity_status,
                identity_reason_codes=reason_codes,
                anchor_entity_id=anchor_entity_id,
                mapping_status=mapping_status,
                review_status=occurrence.review_status,
                review_decision=occurrence.review_decision,
                decision_scope=occurrence.decision_scope,
                updated_at=occurrence.updated_at,
            )
        )
    return entries


def _detected_identity(
    bound: AnchorBoundPiiEntityV1, mapping_status: PiiEntityMappingStatus
) -> tuple[str, list[PiiEntityReviewReasonCode], str | None]:
    """Classify one bound detection's identity outcome (resolved/unresolved/incompatible)."""
    if "invalid_entity_range" in bound.binding_reasons:
        # The stored entity offsets do not fit inside their own referenced raw text -- a genuine
        # structural break, never an ordinary anchor-binding gap.
        return "incompatible", ["source_range_missing"], None
    if bound.identity_basis in ("anchor_exact", "anchor_partial"):
        return "resolved", [], bound.entity_id
    reasons = identity_reason_codes(bound.binding_status, mapping_status)
    if not reasons:
        reasons = ["evidence_only_identity"]
    return "unresolved", reasons, None


def build_manual_addition_entries(
    *,
    manual_additions: list[PiiManualAddition],
    current_text_artifact_id: str | None,
    text_artifacts_by_id: dict[str, TextArtifact | None],
) -> list[PiiReviewResultEntry]:
    """Build one entry per manual addition from its own stored reverse-projection outcome.

    Never re-attempts anchor binding for a manual addition (ADR-0035 keeps manual additions out of
    the anchor-bound entity contract by design) — reuses ``raw_projection_status`` already resolved
    once at add time (canonical-in/raw-out, ``pii_manual_addition.py``), so the displayed mapping
    quality is never silently upgraded or re-guessed by review. ``text_artifacts_by_id`` maps each
    addition's own ``text_artifact_id`` to the resolved artifact (or ``None`` if that reference no
    longer loads), keyed by the caller so this function never fetches artifacts itself.
    """
    entries = []
    for addition in manual_additions:
        text_artifact = text_artifacts_by_id.get(addition.text_artifact_id)
        reading_text = text_artifact.content.reading_text if text_artifact is not None else None
        reference_broken = text_artifact is None or reading_text is None
        offsets_out_of_bounds = (
            reading_text is not None and addition.canonical_end > len(reading_text)
        )
        if reference_broken or offsets_out_of_bounds:
            identity_status = "incompatible"
            reason_codes: list[PiiEntityReviewReasonCode] = (
                ["source_range_missing"] if reference_broken else ["invalid_entity_range"]
            )
            mapping_status: PiiEntityMappingStatus = "not_applicable"
        elif addition.raw_projection_status == "unmapped":
            identity_status = "unresolved"
            reason_codes = ["reading_text_mapping_missing"]
            mapping_status = _RAW_PROJECTION_TO_MAPPING[addition.raw_projection_status]
        else:
            identity_status = "resolved"
            reason_codes = []
            mapping_status = _RAW_PROJECTION_TO_MAPPING[addition.raw_projection_status]

        entries.append(
            PiiReviewResultEntry(
                entry_id=addition.addition_id,
                origin="manual",
                entity_type=addition.entity_type,
                entity_group_id=None,
                pii_artifact_id=None,
                text_artifact_id=addition.text_artifact_id,
                artifact_currency=(
                    "current"
                    if addition.text_artifact_id == current_text_artifact_id
                    else "stale"
                ),
                identity_status=identity_status,
                identity_reason_codes=reason_codes,
                anchor_entity_id=None,
                mapping_status=mapping_status,
                review_status=addition.review_status,
                review_decision=addition.review_decision,
                decision_scope=("manual_addition" if addition.review_decision else None),
                created_at=addition.created_at,
            )
        )
    return entries


def _anchor_graph(text_artifact: TextArtifact | None) -> DocumentTextAnchorGraphV1 | None:
    if text_artifact is None:
        return None
    package = build_document_text_package(text_artifact)
    return build_document_text_anchor_graph(package)
