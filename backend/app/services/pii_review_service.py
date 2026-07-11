"""Persistence and resolution for PII review-entity decisions (Review L8 slice, PII L11 grouping).

Adds a reviewable entity-group/occurrence layer between immutable PII detection (``pii_result``)
and future pseudonymization. Grouping is a pure, derived view (see ``pii_grouping.py``); review
decisions are a separate additive overlay, appended to a per-document JSONL log and collapsed to
the latest decision per target on read — mirroring the existing PII feedback store, but unlike
that dev-only side-channel this overlay is always available and is the binding input future
pseudonymization work will consume. Neither ``pii_result`` nor its entities/offsets are ever
mutated by a decision; raw and projected offsets stay exactly as detected/projected.

This is not pseudonymization, placeholder generation, or reconstruction/export — it only records
a reviewer's intent (pseudonymize/keep/false_positive) against a stable target. A freshly detected
entity is assumed "pseudonymize" by default; a reviewer only has to act to opt an entity *out* of
pseudonymization ("keep" it as-is, or mark it a "false_positive").
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app import __version__
from app.config import Settings
from app.errors import ApiError
from app.schemas import (
    PiiEntity,
    PiiEntityGroup,
    PiiEntityGroupReview,
    PiiManualAddition,
    PiiManualAdditionAck,
    PiiManualAdditionRecord,
    PiiManualAdditionRequest,
    PiiReviewDecisionAck,
    PiiReviewDecisionRecord,
    PiiReviewDecisionRequest,
    PiiReviewDecisionScope,
    PiiReviewDecisionValue,
    PiiReviewOccurrence,
    PiiReviewResult,
    PiiReviewResultArtifact,
    PiiReviewStatus,
)
from app.services.artifact_service import (
    get_latest_pii_artifact,
    get_latest_pii_review_result_artifact,
    get_latest_text_artifact,
    get_pii_artifact,
    save_pii_review_result_artifact,
)
from app.services.document_service import DocumentNotFoundError, get_document_record
from app.services.pii_grouping import group_pii_entities
from app.services.pii_manual_addition import resolve_canonical_span_to_raw

_REVIEW_DIRECTORY = "review"
_DECISIONS_FILENAME = "pii_review_decisions.jsonl"

# No decision recorded yet is treated the same as an explicit "pseudonymize": that is the assumed
# default outcome for every detected entity. "keep" opts an entity out of pseudonymization while
# keeping it flagged as PII; "false_positive" says it was never PII to begin with (no highlight).
# See docs/engine/review-feedback-levels.md#level-9--confirm--reject.
_DECISION_TO_STATUS: dict[PiiReviewDecisionValue, PiiReviewStatus] = {
    "pseudonymize": "accepted",
    "keep": "kept",
    "false_positive": "rejected",
}


def _status_for(decision: PiiReviewDecisionValue | None) -> PiiReviewStatus:
    """Map a decision (or its absence) to the coarser review status shown in the UI.

    No recorded decision defaults to "accepted" (the implied "pseudonymize" outcome) rather than a
    separate "pending" state — every detected entity is assumed pseudonymize-bound until a
    reviewer explicitly opts it out.
    """
    if decision is None:
        return "accepted"
    return _DECISION_TO_STATUS[decision]


class PiiReviewArtifactNotFoundError(ApiError):
    """Raised when a document has no PII result to review yet."""

    def __init__(self) -> None:
        super().__init__("PII result not found.", 404)


class PiiReviewTargetNotFoundError(ApiError):
    """Raised when a decision references a group/occurrence absent from the latest PII result."""

    def __init__(self) -> None:
        super().__init__(
            "Review decision target does not match any entity group or occurrence in the "
            "current PII result.",
            404,
        )


class PiiReviewResultArtifactNotFoundError(ApiError):
    """Raised when no review-result snapshot has been persisted for a document yet."""

    def __init__(self) -> None:
        super().__init__("No review result snapshot found for this document yet.", 404)


class PiiReviewTextArtifactNotFoundError(ApiError):
    """Raised when a document has no usable text result for manual-addition offsets."""

    def __init__(self) -> None:
        super().__init__("Text result not found.", 404)


class PiiManualAdditionInvalidError(ApiError):
    """Raised when a manual addition's entity type or offsets are invalid for the current run."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, 422)


def get_pii_review_result(
    settings: Settings, document_id: str, artifact_id: str | None = None
) -> PiiReviewResult:
    """Return review state for one exact PII result, or the latest when explicitly omitted."""
    if get_document_record(settings, document_id) is None:
        raise DocumentNotFoundError
    artifact = (
        get_pii_artifact(settings, document_id, artifact_id)
        if artifact_id is not None
        else get_latest_pii_artifact(settings, document_id)
    )
    if artifact is None:
        raise PiiReviewArtifactNotFoundError

    entities = artifact.content.entities
    groups = group_pii_entities(entities)
    decisions = _load_latest_decisions(settings, document_id, artifact.id)
    manual_additions = _load_latest_manual_additions(settings, document_id)
    current_text_artifact_id = _current_text_artifact_id(settings, document_id)
    stale_count = _count_stale_decisions(
        settings, document_id, artifact.id, manual_additions, current_text_artifact_id
    )
    return _build_review_result(
        document_id,
        artifact.id,
        artifact.input_text_artifact_id,
        entities,
        groups,
        decisions,
        manual_additions,
        stale_count,
    )


def get_pii_review_result_artifact(
    settings: Settings, document_id: str
) -> PiiReviewResultArtifact:
    """Return the newest persisted review-result snapshot (Review L8, ADR-0034).

    Distinct from :func:`get_pii_review_result`: this is the durable, immutable-per-run artifact
    written after each recorded decision, not a value recomputed on every call.
    """
    if get_document_record(settings, document_id) is None:
        raise DocumentNotFoundError
    artifact = get_latest_pii_review_result_artifact(settings, document_id)
    if artifact is None:
        raise PiiReviewResultArtifactNotFoundError
    return artifact


def set_pii_review_decision(
    settings: Settings, document_id: str, request: PiiReviewDecisionRequest
) -> PiiReviewDecisionAck:
    """Persist one group-, occurrence-, or manual-addition-level review decision."""
    if get_document_record(settings, document_id) is None:
        raise DocumentNotFoundError
    artifact = get_latest_pii_artifact(settings, document_id)
    if artifact is None:
        raise PiiReviewArtifactNotFoundError

    entities = artifact.content.entities
    groups = group_pii_entities(entities)
    manual_additions = _load_latest_manual_additions(settings, document_id)
    current_text_artifact_id = _current_text_artifact_id(settings, document_id)
    if not _target_exists(
        request.target_type,
        request.target_id,
        entities,
        groups,
        manual_additions,
        current_text_artifact_id,
    ):
        raise PiiReviewTargetNotFoundError

    record = PiiReviewDecisionRecord(
        app_version=__version__,
        recorded_at=_now_utc_iso(),
        document_id=document_id,
        artifact_id=artifact.id,
        text_artifact_id=artifact.input_text_artifact_id,
        target_type=request.target_type,
        target_id=request.target_id,
        decision=request.decision,
        note=request.note,
        source="user",
    )
    _append_review_line(settings, document_id, record)
    _persist_review_result_snapshot(
        settings,
        document_id,
        artifact.id,
        artifact.input_text_artifact_id,
        entities,
        groups,
    )
    return PiiReviewDecisionAck(
        recorded=True,
        target_type=record.target_type,
        target_id=record.target_id,
        decision=record.decision,
        review_status=_DECISION_TO_STATUS[record.decision],
        updated_at=record.recorded_at,
    )


def add_pii_manual_entity(
    settings: Settings, document_id: str, request: PiiManualAdditionRequest
) -> PiiManualAdditionAck:
    """Record a reviewer-added span the engine missed (PII L14 / Review L10, ADR-0035).

    Canonical-text offsets only (into the latest ``reading_text``) -- the reviewer selects in the
    canonical reading-text view, the human-facing default (L10.5). A best-effort raw span is
    resolved via the Text Anchor Graph (``pii_manual_addition.py``); an unresolved raw span is an
    explicit, honest state, never a guess. This never touches ``pii_result`` or the anchor-bound
    entity contract; the addition is layered onto the same review-decision log/artifact instead.
    """
    if get_document_record(settings, document_id) is None:
        raise DocumentNotFoundError
    pii_artifact = get_latest_pii_artifact(settings, document_id)
    if pii_artifact is None:
        raise PiiReviewArtifactNotFoundError
    text_artifact = get_latest_text_artifact(settings, document_id)
    if text_artifact is None or not text_artifact.content.reading_text:
        raise PiiReviewTextArtifactNotFoundError

    if request.entity_type not in pii_artifact.content.configured_entity_types:
        raise PiiManualAdditionInvalidError(
            "Entity type is not configured for the current PII run."
        )
    if request.canonical_end > len(text_artifact.content.reading_text):
        raise PiiManualAdditionInvalidError(
            "Canonical offsets exceed the current reading text."
        )

    raw_range, raw_projection_status = resolve_canonical_span_to_raw(
        text_artifact, request.canonical_start, request.canonical_end
    )
    raw_start, raw_end = raw_range if raw_range is not None else (None, None)

    record = PiiManualAdditionRecord(
        app_version=__version__,
        recorded_at=_now_utc_iso(),
        document_id=document_id,
        addition_id=uuid4().hex,
        pii_artifact_id=pii_artifact.id,
        text_artifact_id=text_artifact.id,
        entity_type=request.entity_type,
        canonical_start=request.canonical_start,
        canonical_end=request.canonical_end,
        raw_start=raw_start,
        raw_end=raw_end,
        raw_projection_status=raw_projection_status,
        note=request.note,
    )
    _append_review_line(settings, document_id, record)
    entities = pii_artifact.content.entities
    _persist_review_result_snapshot(
        settings,
        document_id,
        pii_artifact.id,
        pii_artifact.input_text_artifact_id,
        entities,
        group_pii_entities(entities),
    )
    return PiiManualAdditionAck(
        recorded=True,
        addition_id=record.addition_id,
        entity_type=record.entity_type,
        canonical_start=record.canonical_start,
        canonical_end=record.canonical_end,
        raw_projection_status=record.raw_projection_status,
        created_at=record.recorded_at,
    )


def _persist_review_result_snapshot(
    settings: Settings,
    document_id: str,
    artifact_id: str,
    text_artifact_id: str,
    entities: list[PiiEntity],
    groups: list[PiiEntityGroup],
) -> None:
    """Save an immutable snapshot of the fully-resolved review state (Review L8, ADR-0034).

    Reads back the just-written decision/addition (via the same loaders, unchanged) so the snapshot
    reflects exactly what a subsequent ``GET …/pii/review`` would compute -- this function never
    resolves decisions itself, only persists the same resolution as a durable artifact.
    """
    decisions = _load_latest_decisions(settings, document_id, artifact_id)
    manual_additions = _load_latest_manual_additions(settings, document_id)
    current_text_artifact_id = _current_text_artifact_id(settings, document_id)
    stale_count = _count_stale_decisions(
        settings, document_id, artifact_id, manual_additions, current_text_artifact_id
    )
    content = _build_review_result(
        document_id,
        artifact_id,
        text_artifact_id,
        entities,
        groups,
        decisions,
        manual_additions,
        stale_count,
    )
    snapshot = PiiReviewResultArtifact(
        id=uuid4().hex,
        document_id=document_id,
        input_pii_artifact_id=artifact_id,
        input_text_artifact_id=text_artifact_id,
        created_at=_now_utc_iso(),
        content=content,
    )
    save_pii_review_result_artifact(settings, snapshot)


def _target_exists(
    target_type: PiiReviewDecisionScope,
    target_id: str,
    entities: list[PiiEntity],
    groups: list[PiiEntityGroup],
    manual_additions: dict[str, PiiManualAdditionRecord],
    current_text_artifact_id: str | None,
) -> bool:
    if target_type == "occurrence":
        return any(entity.id == target_id for entity in entities)
    if target_type == "manual_addition":
        addition = manual_additions.get(target_id)
        return (
            addition is not None
            and current_text_artifact_id is not None
            and addition.text_artifact_id == current_text_artifact_id
        )
    return any(group.entity_group_id == target_id for group in groups)


def _current_text_artifact_id(settings: Settings, document_id: str) -> str | None:
    text_artifact = get_latest_text_artifact(settings, document_id)
    return text_artifact.id if text_artifact is not None else None


def _build_review_result(
    document_id: str,
    artifact_id: str,
    text_artifact_id: str,
    entities: list[PiiEntity],
    groups: list[PiiEntityGroup],
    decisions: dict[tuple[str, str], PiiReviewDecisionRecord],
    manual_additions: dict[str, PiiManualAdditionRecord],
    stale_decision_count: int,
) -> PiiReviewResult:
    manual_addition_decisions = {
        target_id: record
        for (target_type, target_id), record in decisions.items()
        if target_type == "manual_addition"
    }
    review_manual_additions = [
        PiiManualAddition(
            addition_id=addition.addition_id,
            entity_type=addition.entity_type,
            canonical_start=addition.canonical_start,
            canonical_end=addition.canonical_end,
            text_artifact_id=addition.text_artifact_id,
            raw_start=addition.raw_start,
            raw_end=addition.raw_end,
            raw_projection_status=addition.raw_projection_status,
            note=addition.note,
            created_at=addition.recorded_at,
            review_status=_status_for(decision_record.decision if decision_record else None),
            review_decision=decision_record.decision if decision_record else None,
        )
        for addition in sorted(
            manual_additions.values(), key=lambda item: (item.canonical_start, item.addition_id)
        )
        for decision_record in [manual_addition_decisions.get(addition.addition_id)]
    ]

    group_id_by_occurrence = {
        occurrence_id: group.entity_group_id
        for group in groups
        for occurrence_id in group.occurrence_ids
    }
    group_decisions = {
        target_id: record
        for (target_type, target_id), record in decisions.items()
        if target_type == "entity_group"
    }
    occurrence_decisions = {
        target_id: record
        for (target_type, target_id), record in decisions.items()
        if target_type == "occurrence"
    }

    review_groups = [
        PiiEntityGroupReview(
            **group.model_dump(),
            review_status=_status_for(decision_record.decision if decision_record else None),
            review_decision=decision_record.decision if decision_record else None,
            updated_at=decision_record.recorded_at if decision_record else None,
        )
        for group in groups
        for decision_record in [group_decisions.get(group.entity_group_id)]
    ]

    review_occurrences = []
    for entity in entities:
        group_id = group_id_by_occurrence[entity.id]
        occurrence_decision = occurrence_decisions.get(entity.id)
        if occurrence_decision is not None:
            decision: PiiReviewDecisionValue | None = occurrence_decision.decision
            scope: PiiReviewDecisionScope | None = "occurrence"
        else:
            group_decision = group_decisions.get(group_id)
            decision = group_decision.decision if group_decision else None
            scope = "entity_group" if group_decision else None
        review_occurrences.append(
            PiiReviewOccurrence(
                occurrence_id=entity.id,
                entity_type=entity.entity_type,
                entity_group_id=group_id,
                raw_start=entity.start_offset,
                raw_end=entity.end_offset,
                score=entity.score,
                recognizer=entity.recognizer,
                projection_status=entity.projection_status,
                projection_method=entity.projection_method,
                reading_start_offset=entity.reading_start_offset,
                reading_end_offset=entity.reading_end_offset,
                review_status=_status_for(decision),
                review_decision=decision,
                decision_scope=scope,
            )
        )

    return PiiReviewResult(
        document_id=document_id,
        artifact_id=artifact_id,
        input_text_artifact_id=text_artifact_id,
        groups=review_groups,
        occurrences=review_occurrences,
        manual_additions=review_manual_additions,
        stale_decision_count=stale_decision_count,
        has_stale_decisions=stale_decision_count > 0,
    )


def _load_latest_decisions(
    settings: Settings, document_id: str, artifact_id: str
) -> dict[tuple[str, str], PiiReviewDecisionRecord]:
    """Collapse the append-only log to the latest decision line per (target_type, target_id).

    Entity-group/occurrence decisions are only considered when recorded against the exact current
    PII artifact, so they never silently reapply across a re-run that produced a new artifact id.
    Manual-addition decisions have no ``pii_result`` origin to scope against -- a manual addition
    and its decisions persist across PII re-runs regardless of ``artifact_id``; only a new *text*
    artifact affects their continued validity (see ``_count_stale_decisions``/``_target_exists``).
    """
    path = _decisions_path(settings, document_id)
    latest: dict[tuple[str, str], PiiReviewDecisionRecord] = {}
    if not path.is_file():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        record = _parse_line(line)
        if not isinstance(record, PiiReviewDecisionRecord):
            continue
        if record.target_type != "manual_addition" and record.artifact_id != artifact_id:
            continue
        latest[(record.target_type, record.target_id)] = record
    return latest


def _load_latest_manual_additions(
    settings: Settings, document_id: str
) -> dict[str, PiiManualAdditionRecord]:
    """Collapse the append-only log to the latest manual-addition line per ``addition_id``.

    Loads every manual addition ever recorded for this document -- a manual addition is an
    independent, persistent review item, not scoped to a specific ``pii_result`` the way detected
    occurrences are. Whether its canonical offsets still apply to the *current* text is a separate,
    explicit signal (``_count_stale_decisions``), never a silent drop here.
    """
    path = _decisions_path(settings, document_id)
    latest: dict[str, PiiManualAdditionRecord] = {}
    if not path.is_file():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        record = _parse_line(line)
        if not isinstance(record, PiiManualAdditionRecord):
            continue
        latest[record.addition_id] = record
    return latest


def _count_stale_decisions(
    settings: Settings,
    document_id: str,
    current_artifact_id: str,
    manual_additions: dict[str, PiiManualAdditionRecord],
    current_text_artifact_id: str | None,
) -> int:
    """Count review items that exist but no longer apply because their basis was re-run since.

    For entity-group/occurrence decisions: mirrors ``_load_latest_decisions``'s latest-line-per-
    target collapse, but across *every* PII artifact id ever recorded for this document, then counts
    how many of those latest-per-target records target a different id than ``current_artifact_id``.
    For manual additions: counts every addition whose ``text_artifact_id`` differs from
    ``current_text_artifact_id`` (a manual addition has no ``pii_result`` origin, so a PII re-run
    alone never makes it stale -- only a new *text* artifact can). Neither path changes which
    decision/addition applies; both only make visible what was previously silent.
    """
    stale = 0
    path = _decisions_path(settings, document_id)
    if path.is_file():
        latest_by_target: dict[tuple[str, str], PiiReviewDecisionRecord] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            record = _parse_line(line)
            if not isinstance(record, PiiReviewDecisionRecord):
                continue
            latest_by_target[(record.target_type, record.target_id)] = record
        stale += sum(
            1
            for (target_type, _target_id), record in latest_by_target.items()
            if target_type != "manual_addition" and record.artifact_id != current_artifact_id
        )
    stale += sum(
        1
        for addition in manual_additions.values()
        if addition.text_artifact_id != current_text_artifact_id
    )
    return stale


def _parse_line(line: str) -> PiiReviewDecisionRecord | PiiManualAdditionRecord | None:
    """Parse one JSONL line, dispatching on ``record_type`` (legacy lines default to "decision")."""
    stripped = line.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    record_type = payload.get("record_type", "decision")
    try:
        if record_type == "manual_addition":
            return PiiManualAdditionRecord.model_validate(payload)
        return PiiReviewDecisionRecord.model_validate(payload)
    except ValidationError:
        return None


def _append_review_line(
    settings: Settings,
    document_id: str,
    record: PiiReviewDecisionRecord | PiiManualAdditionRecord,
) -> None:
    path = _decisions_path(settings, document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = record.model_dump_json() + "\n"
    try:
        with path.open("a", encoding="utf-8") as decisions_file:
            decisions_file.write(line)
            decisions_file.flush()
            os.fsync(decisions_file.fileno())
    except OSError as exc:  # pragma: no cover - surfaced as a clean 500 by the handler
        raise ApiError("Review decision could not be stored.", 500) from exc


def _decisions_path(settings: Settings, document_id: str) -> Path:
    return settings.document_data_dir / document_id / _REVIEW_DIRECTORY / _DECISIONS_FILENAME


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
