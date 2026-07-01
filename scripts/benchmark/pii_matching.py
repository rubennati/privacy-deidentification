"""Entity-type mapping and TP/FP/FN matching between detected PII and candidate ground truth.

Ground truth is a *candidate* benchmark (deterministic heuristics over extracted page text), not
a manually validated gold standard — matching here is deliberately pragmatic and transparent
rather than aggressive. See the module docstring notes below each mapping decision.

Only ``entity_type``, ``page``, and offsets are ever compared. No raw or masked value is read,
compared, or returned by this module.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from artifact_loader import DetectedEntity
from document_matching import GroundTruthEntityAnchor

# Ground-truth/detected entity type name -> canonical type name. Unknown types pass through
# unchanged (canonicalize() falls back to the input), so nothing is silently dropped.
CANONICAL_TYPE_MAP: dict[str, str] = {
    # structured
    "EMAIL": "EMAIL_ADDRESS",
    "EMAIL_ADDRESS": "EMAIL_ADDRESS",
    "PHONE": "PHONE_NUMBER",
    "PHONE_NUMBER": "PHONE_NUMBER",
    "IBAN": "IBAN_CODE",
    "IBAN_CODE": "IBAN_CODE",
    "CREDIT_CARD": "CREDIT_CARD",
    "IP": "IP_ADDRESS",
    "IP_ADDRESS": "IP_ADDRESS",
    "URL": "URL",
    # NER
    "PERSON": "PERSON",
    "PERSON_NAME": "PERSON",
    "ORG": "ORGANIZATION",
    "ORGANIZATION": "ORGANIZATION",
    "LOC": "LOCATION",
    "LOCATION": "LOCATION",
    "ADDRESS": "ADDRESS",
    "DATE": "DATE_TIME",
    "DATE_TIME": "DATE_TIME",
    # BIRTH_DATE is deliberately NOT folded into DATE_TIME: it is a distinct, more sensitive
    # concept the current pipeline has no dedicated recognizer for. Merging it would inflate
    # recall without the pipeline actually distinguishing birthdates from generic dates.
    "BIRTH_DATE": "BIRTH_DATE",
    # Austrian / domain-sensitive identifiers: kept under their own canonical name. The Engine-4
    # `insurance-at-de` pack now provides recognizers for these; see
    # `TYPE_GROUPS["domain_sensitive_types"]`.
    "UID_AT": "UID_AT",
    "FN_AT": "FN_AT",
    "SVNR_AT": "SVNR_AT",
    "BIC": "BIC",
    "STEUERNUMMER": "TAX_ID_AT",
    "TAX_ID": "TAX_ID_AT",
    "TAX_ID_AT": "TAX_ID_AT",
    "POLIZZENUMMER": "POLICY_NUMBER",
    "SCHADENNUMMER": "CLAIM_NUMBER",
    "VERTRAGSNUMMER": "CONTRACT_NUMBER",
    "AKTENZEICHEN": "CASE_NUMBER",
    "RECHNUNGSNUMMER": "INVOICE_NUMBER",
    "ANGEBOTSNUMMER": "OFFER_NUMBER",
    "KUNDENNUMMER": "CUSTOMER_NUMBER",
    "KFZ_KENNZEICHEN": "LICENSE_PLATE_AT",
    "LICENSE_PLATE": "LICENSE_PLATE_AT",
    "LICENSE_PLATE_AT": "LICENSE_PLATE_AT",
    "REISEPASS": "PASSPORT_NUMBER",
    "PERSONALAUSWEIS": "ID_CARD_NUMBER",
    "FILE_REFERENCE": "FILE_REFERENCE",
    "BERICHTSNUMMER": "REPORT_NUMBER",
    "REPORT_NUMBER": "REPORT_NUMBER",
    "GUTACHTENNUMMER": "ASSESSMENT_NUMBER",
    "ASSESSMENT_NUMBER": "ASSESSMENT_NUMBER",
    "PROJECT_ID": "PROJECT_ID",
    "TRANSACTION_ID": "TRANSACTION_ID",
    "USER_ID": "USER_ID",
}

TYPE_GROUPS: dict[str, frozenset[str]] = {
    "structured_types": frozenset(
        {"EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD", "IP_ADDRESS", "URL"}
    ),
    "ner_types": frozenset({"PERSON", "ORGANIZATION", "LOCATION", "DATE_TIME"}),
    "domain_sensitive_types": frozenset(
        {
            "UID_AT",
            "FN_AT",
            "SVNR_AT",
            "TAX_ID_AT",
            "POLICY_NUMBER",
            "CLAIM_NUMBER",
            "CONTRACT_NUMBER",
            "CASE_NUMBER",
            "INVOICE_NUMBER",
            "OFFER_NUMBER",
            "CUSTOMER_NUMBER",
            "LICENSE_PLATE_AT",
            "PASSPORT_NUMBER",
            "ID_CARD_NUMBER",
            "BIC",
            "FILE_REFERENCE",
            "REPORT_NUMBER",
            "ASSESSMENT_NUMBER",
            "PROJECT_ID",
            "TRANSACTION_ID",
            "USER_ID",
        }
    ),
}
_OTHER_GROUP = "other_types"


def canonicalize(entity_type: str) -> str:
    """Map a raw entity type name to its canonical name (identity if unmapped)."""
    return CANONICAL_TYPE_MAP.get(entity_type, entity_type)


def type_group(canonical_type: str) -> str:
    for group_name, members in TYPE_GROUPS.items():
        if canonical_type in members:
            return group_name
    return _OTHER_GROUP


def spans_overlap_enough(
    a_start: int,
    a_end: int,
    b_start: int,
    b_end: int,
    min_overlap_ratio: float = 0.5,
    start_tolerance: int = 10,
) -> bool:
    """True if two spans overlap by at least ``min_overlap_ratio`` of the shorter span, or their
    start positions are within ``start_tolerance`` characters of each other."""
    overlap = max(0, min(a_end, b_end) - max(a_start, b_start))
    shorter_len = min(a_end - a_start, b_end - b_start)
    if shorter_len > 0 and overlap / shorter_len >= min_overlap_ratio:
        return True
    return abs(a_start - b_start) <= start_tolerance


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


@dataclass(frozen=True)
class EntityTypeMetrics:
    entity_type: str
    expected_count: int
    detected_count: int
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float


def _type_metrics(entity_type: str, tp: int, fp: int, fn: int) -> EntityTypeMetrics:
    precision, recall, f1 = precision_recall_f1(tp, fp, fn)
    return EntityTypeMetrics(
        entity_type=entity_type,
        expected_count=tp + fn,
        detected_count=tp + fp,
        tp=tp,
        fp=fp,
        fn=fn,
        precision=precision,
        recall=recall,
        f1=f1,
    )


@dataclass(frozen=True)
class DocumentPiiMatchResult:
    matching_mode: str  # "page_aware" | "document_level"
    tp: int
    fp: int
    fn: int
    by_type: tuple[EntityTypeMetrics, ...]


def match_document_entities(
    detected: Sequence[DetectedEntity],
    groundtruth: Sequence[GroundTruthEntityAnchor],
    matching_mode: str,
) -> DocumentPiiMatchResult:
    """Match one document's detected entities against its candidate ground truth.

    ``page_aware``: greedy bipartite matching per ground-truth entity, restricted to the same
    page, compatible canonical type, and an overlapping page-local offset span.
    ``document_level``: no page/offset information is available (e.g. DOCX); entities are
    matched by canonical type counts only, per the PR spec's documented fallback.
    """
    if matching_mode == "page_aware":
        return _match_page_aware(detected, groundtruth)
    return _match_document_level(detected, groundtruth)


def _match_page_aware(
    detected: Sequence[DetectedEntity], groundtruth: Sequence[GroundTruthEntityAnchor]
) -> DocumentPiiMatchResult:
    used_detected: set[int] = set()
    type_tp: dict[str, int] = {}
    type_fn: dict[str, int] = {}

    for gt in groundtruth:
        gt_canonical = canonicalize(gt.entity_type)
        candidate_indices = [
            index
            for index, entity in enumerate(detected)
            if index not in used_detected
            and canonicalize(entity.entity_type) == gt_canonical
            and entity.page_number == gt.page
            and entity.page_start_offset is not None
            and entity.page_end_offset is not None
            and spans_overlap_enough(
                entity.page_start_offset, entity.page_end_offset, gt.start, gt.end
            )
        ]
        if candidate_indices:
            best = min(
                candidate_indices,
                key=lambda index: abs((detected[index].page_start_offset or 0) - gt.start),
            )
            used_detected.add(best)
            type_tp[gt_canonical] = type_tp.get(gt_canonical, 0) + 1
        else:
            type_fn[gt_canonical] = type_fn.get(gt_canonical, 0) + 1

    type_fp: dict[str, int] = {}
    for index, entity in enumerate(detected):
        if index in used_detected:
            continue
        canonical = canonicalize(entity.entity_type)
        type_fp[canonical] = type_fp.get(canonical, 0) + 1

    return _build_result("page_aware", type_tp, type_fp, type_fn)


def _match_document_level(
    detected: Sequence[DetectedEntity], groundtruth: Sequence[GroundTruthEntityAnchor]
) -> DocumentPiiMatchResult:
    expected_counts: dict[str, int] = {}
    for gt in groundtruth:
        canonical = canonicalize(gt.entity_type)
        expected_counts[canonical] = expected_counts.get(canonical, 0) + 1

    detected_counts: dict[str, int] = {}
    for entity in detected:
        canonical = canonicalize(entity.entity_type)
        detected_counts[canonical] = detected_counts.get(canonical, 0) + 1

    type_tp: dict[str, int] = {}
    type_fp: dict[str, int] = {}
    type_fn: dict[str, int] = {}
    for canonical in set(expected_counts) | set(detected_counts):
        expected = expected_counts.get(canonical, 0)
        found = detected_counts.get(canonical, 0)
        tp = min(expected, found)
        type_tp[canonical] = tp
        type_fp[canonical] = found - tp
        type_fn[canonical] = expected - tp

    return _build_result("document_level", type_tp, type_fp, type_fn)


def _build_result(
    matching_mode: str,
    type_tp: dict[str, int],
    type_fp: dict[str, int],
    type_fn: dict[str, int],
) -> DocumentPiiMatchResult:
    all_types = sorted(set(type_tp) | set(type_fp) | set(type_fn))
    by_type = tuple(
        _type_metrics(t, type_tp.get(t, 0), type_fp.get(t, 0), type_fn.get(t, 0))
        for t in all_types
    )
    return DocumentPiiMatchResult(
        matching_mode=matching_mode,
        tp=sum(type_tp.values()),
        fp=sum(type_fp.values()),
        fn=sum(type_fn.values()),
        by_type=by_type,
    )


def merge_type_metrics(groups: Sequence[Sequence[EntityTypeMetrics]]) -> tuple[EntityTypeMetrics, ...]:
    """Sum per-type TP/FP/FN across multiple documents into corpus-wide per-type metrics."""
    tp: dict[str, int] = {}
    fp: dict[str, int] = {}
    fn: dict[str, int] = {}
    for group in groups:
        for metric in group:
            tp[metric.entity_type] = tp.get(metric.entity_type, 0) + metric.tp
            fp[metric.entity_type] = fp.get(metric.entity_type, 0) + metric.fp
            fn[metric.entity_type] = fn.get(metric.entity_type, 0) + metric.fn
    all_types = sorted(set(tp) | set(fp) | set(fn))
    return tuple(
        _type_metrics(t, tp.get(t, 0), fp.get(t, 0), fn.get(t, 0)) for t in all_types
    )


@dataclass(frozen=True)
class DocumentPiiMetrics:
    document_id: str
    display_filename: str
    matching_mode: str
    expected_candidate_count: int
    detected_entity_count: int
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    missing_entity_types: tuple[str, ...]
    extra_entity_types: tuple[str, ...]
    unsupported_entity_types: tuple[str, ...]
    by_type: tuple[EntityTypeMetrics, ...]


@dataclass(frozen=True)
class GlobalPiiMetrics:
    total_expected: int
    total_detected: int
    total_tp: int
    total_fp: int
    total_fn: int
    precision: float
    recall: float
    f1: float
    by_type: tuple[EntityTypeMetrics, ...]
    by_type_group: dict[str, EntityTypeMetrics]
    unsupported_entity_types: tuple[str, ...]


def build_document_pii_metrics(
    document_id: str,
    display_filename: str,
    detected: Sequence[DetectedEntity],
    configured_entity_types: Sequence[str],
    groundtruth: Sequence[GroundTruthEntityAnchor],
    matching_mode: str,
) -> DocumentPiiMetrics:
    """Compose matching + type mapping into one document's reportable PII metrics."""
    result = match_document_entities(detected, groundtruth, matching_mode)
    precision, recall, f1 = precision_recall_f1(result.tp, result.fp, result.fn)
    configured_canonical = {canonicalize(t) for t in configured_entity_types}
    gt_canonical_types = {canonicalize(gt.entity_type) for gt in groundtruth}

    missing = tuple(sorted(m.entity_type for m in result.by_type if m.fn > 0))
    extra = tuple(sorted(m.entity_type for m in result.by_type if m.fp > 0))
    unsupported = tuple(sorted(t for t in gt_canonical_types if t not in configured_canonical))

    return DocumentPiiMetrics(
        document_id=document_id,
        display_filename=display_filename,
        matching_mode=matching_mode,
        expected_candidate_count=len(groundtruth),
        detected_entity_count=len(detected),
        tp=result.tp,
        fp=result.fp,
        fn=result.fn,
        precision=precision,
        recall=recall,
        f1=f1,
        missing_entity_types=missing,
        extra_entity_types=extra,
        unsupported_entity_types=unsupported,
        by_type=result.by_type,
    )


def build_global_pii_metrics(per_document: Sequence[DocumentPiiMetrics]) -> GlobalPiiMetrics:
    """Aggregate per-document PII metrics into corpus-wide totals, per-type, and per-group."""
    total_tp = sum(doc.tp for doc in per_document)
    total_fp = sum(doc.fp for doc in per_document)
    total_fn = sum(doc.fn for doc in per_document)
    precision, recall, f1 = precision_recall_f1(total_tp, total_fp, total_fn)
    by_type = merge_type_metrics([doc.by_type for doc in per_document])

    group_tp: dict[str, int] = {}
    group_fp: dict[str, int] = {}
    group_fn: dict[str, int] = {}
    for metric in by_type:
        group = type_group(metric.entity_type)
        group_tp[group] = group_tp.get(group, 0) + metric.tp
        group_fp[group] = group_fp.get(group, 0) + metric.fp
        group_fn[group] = group_fn.get(group, 0) + metric.fn
    by_group = {
        group: _type_metrics(group, group_tp[group], group_fp.get(group, 0), group_fn.get(group, 0))
        for group in group_tp
    }

    unsupported = tuple(
        sorted({entity_type for doc in per_document for entity_type in doc.unsupported_entity_types})
    )

    return GlobalPiiMetrics(
        total_expected=sum(doc.expected_candidate_count for doc in per_document),
        total_detected=sum(doc.detected_entity_count for doc in per_document),
        total_tp=total_tp,
        total_fp=total_fp,
        total_fn=total_fn,
        precision=precision,
        recall=recall,
        f1=f1,
        by_type=by_type,
        by_type_group=by_group,
        unsupported_entity_types=unsupported,
    )
