"""Synthetic acceptance scenarios: the boundary metric must register the structural-context
stage's two effects (ADR-0043) on the patterns the thin real corpus lacks.

These fixtures model the stage's *before* (raw detections) vs *after* (clipped/dropped detections)
output — the stage itself is exercised in the backend unit tests
(``backend/tests/test_pii_structural_validation.py``). Here we prove the benchmark's scoring
substrate credits that transformation: a cross-cell overflow that a lenient TP hides becomes a
visible boundary gain, and an ADDRESS-as-heading false positive becomes a precision gain — both
with no true-positive loss. All data is synthetic (offsets only, no document text).
"""

from __future__ import annotations

from artifact_loader import DetectedEntity
from document_matching import GroundTruthEntityAnchor
from pii_matching import build_document_pii_metrics


def _detected(entity_type: str, page: int, start: int, end: int) -> DetectedEntity:
    return DetectedEntity(
        entity_type=entity_type,
        page_number=page,
        start_offset=start,
        end_offset=end,
        page_start_offset=start,
        page_end_offset=end,
        recognizer="Structural",
        score=0.9,
    )


def _gt(entity_type: str, page: int, start: int, end: int) -> GroundTruthEntityAnchor:
    return GroundTruthEntityAnchor(entity_type=entity_type, page=page, start=start, end=end)


def _metrics(detected: list[DetectedEntity], groundtruth: list[GroundTruthEntityAnchor]):
    return build_document_pii_metrics(
        "doc", "synthetic.pdf", detected, ["ADDRESS"], groundtruth, "page_aware"
    )


# --- Cross-cell overflow: a clip is invisible to TP/FP/FN but visible to boundary accuracy --------


def test_cross_cell_overflow_clip_is_a_boundary_gain_not_a_score_change() -> None:
    gt = [_gt("ADDRESS", 1, 100, 130)]  # the true address, confined to its table cell
    before = _metrics([_detected("ADDRESS", 1, 100, 155)], gt)  # bleeds into the next cell
    after = _metrics([_detected("ADDRESS", 1, 100, 130)], gt)  # structural cell-clip applied

    # The lenient matcher scored both as the same TP — no regression, no false gain.
    assert (before.tp, before.fp, before.fn) == (after.tp, after.fp, after.fn) == (1, 0, 0)
    # ...but the clip is now measurable.
    assert after.boundary.iou_mean > before.boundary.iou_mean
    assert before.boundary.exact_rate == 0.0
    assert after.boundary.exact_rate == 1.0


# --- ADDRESS-as-heading: dropping the false positive is a precision gain with no recall loss ------


def test_heading_false_positive_drop_is_a_precision_gain_no_recall_loss() -> None:
    gt = [_gt("ADDRESS", 1, 200, 230)]  # one real address
    before = _metrics(
        [_detected("ADDRESS", 1, 200, 230), _detected("ADDRESS", 1, 0, 25)], gt
    )  # real + a heading captured as ADDRESS
    after = _metrics([_detected("ADDRESS", 1, 200, 230)], gt)  # heading rejected

    assert (before.tp, before.fp, before.fn) == (1, 1, 0)
    assert (after.tp, after.fp, after.fn) == (1, 0, 0)
    assert after.precision > before.precision  # 1.0 > 0.5
    assert after.recall == before.recall == 1.0  # no true positive lost


# --- Combined realistic document: the full acceptance criterion in one measurement ---------------


def test_combined_document_shows_fp_down_boundary_up_and_no_tp_loss() -> None:
    gt = [_gt("ADDRESS", 1, 100, 130), _gt("ADDRESS", 1, 200, 230)]
    before = _metrics(
        [
            _detected("ADDRESS", 1, 100, 155),  # cross-cell overflow
            _detected("ADDRESS", 1, 200, 230),  # clean
            _detected("ADDRESS", 1, 0, 25),  # heading FP
        ],
        gt,
    )
    after = _metrics(
        [
            _detected("ADDRESS", 1, 100, 130),  # clipped
            _detected("ADDRESS", 1, 200, 230),  # clean
            # heading dropped
        ],
        gt,
    )

    assert before.tp == after.tp == 2  # no true positive lost
    assert before.fp == 1 and after.fp == 0  # false positive removed
    assert after.precision > before.precision
    assert after.boundary.iou_mean > before.boundary.iou_mean
    assert after.boundary.exact_rate == 1.0
