from __future__ import annotations

from artifact_loader import DetectedEntity, ValidationSummary
from document_matching import GroundTruthEntityAnchor
from pii_matching import (
    BoundaryAccuracy,
    aggregate_validation_summaries,
    build_document_pii_metrics,
    build_global_pii_metrics,
    canonicalize,
    match_document_entities,
    span_iou,
    spans_overlap_enough,
    type_group,
)


def _detected(
    entity_type: str,
    page: int | None,
    start: int,
    end: int,
    page_start: int | None = None,
    page_end: int | None = None,
) -> DetectedEntity:
    return DetectedEntity(
        entity_type=entity_type,
        page_number=page,
        start_offset=start,
        end_offset=end,
        page_start_offset=page_start if page_start is not None else start,
        page_end_offset=page_end if page_end is not None else end,
        recognizer="TestRecognizer",
        score=0.9,
    )


def _gt(entity_type: str, page: int | None, start: int, end: int) -> GroundTruthEntityAnchor:
    return GroundTruthEntityAnchor(entity_type=entity_type, page=page, start=start, end=end)


def test_canonicalize_maps_known_aliases() -> None:
    assert canonicalize("EMAIL") == "EMAIL_ADDRESS"
    assert canonicalize("PERSON_NAME") == "PERSON"
    assert canonicalize("ORG") == "ORGANIZATION"
    assert canonicalize("DATE") == "DATE_TIME"
    assert canonicalize("STEUERNUMMER") == "TAX_ID_AT"
    assert canonicalize("KFZ_KENNZEICHEN") == "LICENSE_PLATE_AT"
    assert canonicalize("GUTACHTENNUMMER") == "ASSESSMENT_NUMBER"


def test_canonicalize_keeps_birth_date_distinct_from_date_time() -> None:
    assert canonicalize("BIRTH_DATE") == "BIRTH_DATE"
    assert canonicalize("BIRTH_DATE") != canonicalize("DATE")


def test_canonicalize_passes_through_unknown_types() -> None:
    assert canonicalize("SOME_NEW_TYPE") == "SOME_NEW_TYPE"


def test_type_group_buckets_structured_ner_domain_and_other() -> None:
    assert type_group("EMAIL_ADDRESS") == "structured_types"
    assert type_group("PERSON") == "ner_types"
    assert type_group("UID_AT") == "domain_sensitive_types"
    assert type_group("ASSESSMENT_NUMBER") == "domain_sensitive_types"
    assert type_group("USER_ID") == "domain_sensitive_types"
    assert type_group("ADDRESS") == "address_contact_types"
    assert type_group("CONTACT_LINE") == "address_contact_types"
    assert type_group("CUSTOMER_LINE") == "address_contact_types"
    assert type_group("BIRTH_DATE") == "other_types"


def test_spans_overlap_enough_by_ratio() -> None:
    assert spans_overlap_enough(0, 10, 5, 12) is True  # 5-char overlap of a 7/10-char span
    assert spans_overlap_enough(0, 10, 100, 110) is False


def test_spans_overlap_enough_by_start_tolerance() -> None:
    # No real overlap, but start positions are close enough.
    assert spans_overlap_enough(0, 5, 8, 13, start_tolerance=10) is True
    assert spans_overlap_enough(0, 5, 50, 55, start_tolerance=10) is False


def test_match_document_entities_page_aware_true_positive() -> None:
    detected = [_detected("EMAIL_ADDRESS", 1, 10, 30)]
    groundtruth = [_gt("EMAIL", 1, 10, 30)]
    result = match_document_entities(detected, groundtruth, "page_aware")
    assert result.tp == 1
    assert result.fp == 0
    assert result.fn == 0


def test_match_document_entities_page_aware_false_negative_wrong_page() -> None:
    detected = [_detected("EMAIL_ADDRESS", 2, 10, 30)]
    groundtruth = [_gt("EMAIL", 1, 10, 30)]
    result = match_document_entities(detected, groundtruth, "page_aware")
    assert result.tp == 0
    assert result.fn == 1
    assert result.fp == 1


def test_match_document_entities_page_aware_false_positive_extra_detection() -> None:
    detected = [_detected("EMAIL_ADDRESS", 1, 10, 30), _detected("PERSON", 1, 50, 60)]
    groundtruth = [_gt("EMAIL", 1, 10, 30)]
    result = match_document_entities(detected, groundtruth, "page_aware")
    assert result.tp == 1
    assert result.fp == 1
    assert result.fn == 0


def test_match_document_entities_document_level_fallback_counts_only() -> None:
    detected = [_detected("ORGANIZATION", None, 0, 10, None, None) for _ in range(3)]
    groundtruth = [_gt("ORG", None, 0, 0) for _ in range(2)]
    result = match_document_entities(detected, groundtruth, "document_level")
    assert result.matching_mode == "document_level"
    assert result.tp == 2
    assert result.fp == 1
    assert result.fn == 0


def test_build_document_pii_metrics_reports_missing_extra_and_unsupported_types() -> None:
    detected = [_detected("EMAIL_ADDRESS", 1, 0, 10)]
    groundtruth = [_gt("EMAIL", 1, 0, 10), _gt("UID_AT", 1, 100, 110)]
    metrics = build_document_pii_metrics(
        "doc-1", "Report.pdf", detected, ["EMAIL_ADDRESS"], groundtruth, "page_aware"
    )
    assert metrics.tp == 1
    assert metrics.fn == 1
    assert "UID_AT" in metrics.missing_entity_types
    assert "UID_AT" in metrics.unsupported_entity_types
    assert "EMAIL_ADDRESS" not in metrics.unsupported_entity_types


def test_build_document_pii_metrics_extra_type_not_in_groundtruth() -> None:
    detected = [_detected("EMAIL_ADDRESS", 1, 0, 10), _detected("PERSON", 1, 50, 60)]
    groundtruth = [_gt("EMAIL", 1, 0, 10)]
    metrics = build_document_pii_metrics(
        "doc-1", "Report.pdf", detected, ["EMAIL_ADDRESS", "PERSON"], groundtruth, "page_aware"
    )
    assert "PERSON" in metrics.extra_entity_types


def test_build_global_pii_metrics_aggregates_across_documents() -> None:
    doc_a = build_document_pii_metrics(
        "doc-1",
        "A.pdf",
        [_detected("EMAIL_ADDRESS", 1, 0, 10)],
        ["EMAIL_ADDRESS"],
        [_gt("EMAIL", 1, 0, 10)],
        "page_aware",
    )
    doc_b = build_document_pii_metrics(
        "doc-2",
        "B.pdf",
        [],
        ["EMAIL_ADDRESS"],
        [_gt("EMAIL", 1, 0, 10)],
        "page_aware",
    )
    global_metrics = build_global_pii_metrics([doc_a, doc_b])
    assert global_metrics.total_expected == 2
    assert global_metrics.total_tp == 1
    assert global_metrics.total_fn == 1
    assert global_metrics.precision == 1.0
    email_group = global_metrics.by_type_group["structured_types"]
    assert email_group.tp == 1
    assert email_group.fn == 1


def test_aggregate_validation_summaries_sums_counts_and_merges_reasons() -> None:
    doc_a = ValidationSummary(
        enabled=True,
        kept=10,
        dropped=3,
        score_down=2,
        dropped_by_reason={"STOPWORD_ONLY": 2, "GENERIC_DOCUMENT_WORD": 1},
        score_down_by_reason={"ORG_WITHOUT_ORG_SIGNAL": 2},
    )
    doc_b = ValidationSummary(
        enabled=True,
        kept=5,
        dropped=1,
        score_down=0,
        dropped_by_reason={"STOPWORD_ONLY": 1},
        score_down_by_reason={},
    )

    summary = aggregate_validation_summaries([doc_a, doc_b])

    assert summary.documents_considered == 2
    assert summary.documents_with_validation_enabled == 2
    assert summary.total_kept == 15
    assert summary.total_dropped == 4
    assert summary.total_score_down == 2
    assert summary.dropped_by_reason == {"STOPWORD_ONLY": 3, "GENERIC_DOCUMENT_WORD": 1}
    assert summary.score_down_by_reason == {"ORG_WITHOUT_ORG_SIGNAL": 2}


def test_aggregate_validation_summaries_skips_missing_documents() -> None:
    summary = aggregate_validation_summaries(
        [
            None,
            ValidationSummary(
                enabled=False,
                kept=4,
                dropped=0,
                score_down=0,
                dropped_by_reason={},
                score_down_by_reason={},
            ),
        ]
    )

    assert summary.documents_considered == 1
    assert summary.documents_with_validation_enabled == 0
    assert summary.total_kept == 4


def test_aggregate_validation_summaries_handles_empty_input() -> None:
    summary = aggregate_validation_summaries([])

    assert summary.documents_considered == 0
    assert summary.total_kept == 0
    assert summary.dropped_by_reason == {}


# --- Boundary accuracy (additive; credits clip/trim without changing TP/FP/FN) --------------------


def test_span_iou_exact_overlap_and_disjoint() -> None:
    assert span_iou(10, 30, 10, 30) == 1.0
    assert span_iou(0, 10, 100, 110) == 0.0
    # Over-capture: detected [10,40] vs gt [10,30] -> overlap 20 / union 30.
    assert span_iou(10, 40, 10, 30) == 20 / 30


def test_boundary_accuracy_empty_is_zero_without_div_error() -> None:
    empty = BoundaryAccuracy()
    assert empty.matched_pairs == 0
    assert empty.iou_mean == 0.0
    assert empty.exact_rate == 0.0
    assert empty.near_exact_rate == 0.0


def test_exact_match_scores_perfect_boundary() -> None:
    result = match_document_entities(
        [_detected("ADDRESS", 1, 10, 30)], [_gt("ADDRESS", 1, 10, 30)], "page_aware"
    )
    assert (result.tp, result.fp, result.fn) == (1, 0, 0)
    assert result.boundary.matched_pairs == 1
    assert result.boundary.iou_mean == 1.0
    assert result.boundary.exact_rate == 1.0
    assert result.boundary.near_exact_rate == 1.0


def test_over_capture_still_a_lenient_tp_but_low_boundary() -> None:
    # Detected bleeds past the gt end (whole-line ADDRESS). Lenient matcher still counts it a TP.
    result = match_document_entities(
        [_detected("ADDRESS", 1, 10, 40)], [_gt("ADDRESS", 1, 10, 30)], "page_aware"
    )
    assert (result.tp, result.fp, result.fn) == (1, 0, 0)
    assert result.boundary.iou_mean == 20 / 30  # < 0.8
    assert result.boundary.exact_rate == 0.0
    assert result.boundary.near_exact_rate == 0.0


def test_clip_is_measurable_while_tp_fp_fn_unchanged() -> None:
    # The core reason for this metric: an over-capture and its clipped version score IDENTICAL
    # lenient TP/FP/FN, but the clip must be visible as a boundary-accuracy gain.
    gt = [_gt("ADDRESS", 1, 10, 30)]
    over = match_document_entities([_detected("ADDRESS", 1, 10, 40)], gt, "page_aware")
    clipped = match_document_entities([_detected("ADDRESS", 1, 10, 30)], gt, "page_aware")
    assert (over.tp, over.fp, over.fn) == (clipped.tp, clipped.fp, clipped.fn) == (1, 0, 0)
    assert clipped.boundary.iou_mean > over.boundary.iou_mean
    assert clipped.boundary.exact_rate == 1.0 and over.boundary.exact_rate == 0.0


def test_strict_policy_turns_over_capture_into_a_miss() -> None:
    detected = [_detected("ADDRESS", 1, 10, 40)]  # IoU 0.667 vs gt -> below near-exact threshold
    gt = [_gt("ADDRESS", 1, 10, 30)]
    lenient = match_document_entities(detected, gt, "page_aware")
    strict = match_document_entities(detected, gt, "page_aware", boundary_policy="strict")
    assert (lenient.tp, lenient.fp, lenient.fn) == (1, 0, 0)
    assert (strict.tp, strict.fp, strict.fn) == (0, 1, 1)


def test_global_boundary_aggregates_across_documents() -> None:
    gt = [_gt("ADDRESS", 1, 10, 30)]
    doc_exact = build_document_pii_metrics(
        "d1", "A.pdf", [_detected("ADDRESS", 1, 10, 30)], ["ADDRESS"], gt, "page_aware"
    )
    doc_over = build_document_pii_metrics(
        "d2", "B.pdf", [_detected("ADDRESS", 1, 10, 40)], ["ADDRESS"], gt, "page_aware"
    )
    global_metrics = build_global_pii_metrics([doc_exact, doc_over])
    assert global_metrics.boundary.matched_pairs == 2
    assert global_metrics.boundary.exact_count == 1  # only the exact document
    assert global_metrics.boundary.iou_mean == (1.0 + 20 / 30) / 2


def test_document_level_mode_has_no_boundary_pairs() -> None:
    detected = [_detected("ORGANIZATION", None, 0, 10, None, None)]
    result = match_document_entities(detected, [_gt("ORG", None, 0, 0)], "document_level")
    assert result.boundary.matched_pairs == 0
