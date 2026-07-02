"""Assemble the private benchmark's markdown and JSON reports.

Both reports are rendered from one shared, already-PII-free nested dict produced by
``build_report``. Nothing in this module reads a text/value field — everything it touches is
already a count, status, type name, or offset by the time it reaches this module (see
``artifact_loader.py``, ``document_matching.py``, ``ocr_metrics.py``, and ``pii_matching.py``).
``private_benchmark.py`` runs ``privacy_guard.assert_report_is_safe`` on the result before
writing anything to disk.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from artifact_loader import LocalDocument
from document_matching import AmbiguousMatch, MatchedDocument, MatchResult
from ocr_metrics import ArtifactAvailability, DocumentOcrMetrics, OcrAggregateMetrics
from pii_matching import (
    DocumentPiiMetrics,
    EntityTypeMetrics,
    GlobalPiiMetrics,
    ValidationBenchmarkSummary,
)

# Documents called out explicitly in the PR spec because PR #6's text-layer quality gate and
# OCR fallback changed their expected routing.
HIGHLIGHTED_DOCUMENT_STEMS: tuple[str, ...] = (
    "S80286-GA",
    "S80917-GA",
    "S80826-RE",
    "S80998",
    "TEST_01",
    "TEST_02",
    "TEST_03",
    "TEST_04",
)


def _availability_to_dict(availability: ArtifactAvailability) -> dict[str, str]:
    return {
        "audit_result": availability.audit_result,
        "text_result": availability.text_result,
        "quality_report": availability.quality_report,
        "pii_result": availability.pii_result,
    }


def _local_document_to_dict(doc: LocalDocument) -> dict[str, Any]:
    return {
        "document_id": doc.document_id,
        "display_filename": doc.display_filename,
        "storage_filename": doc.storage_filename,
        "mime_type": doc.mime_type,
        "sha256": doc.sha256,
        "size_bytes": doc.size_bytes,
        "created_at": doc.created_at,
        "upload_exists": doc.upload_exists,
        "upload_size_bytes": doc.upload_size_bytes,
    }


def _matched_document_to_dict(match: MatchedDocument) -> dict[str, Any]:
    return {
        "document_id": match.document_id,
        "local_filename": match.local_filename,
        "benchmark_filename": match.benchmark_filename,
        "match_basis": match.match_basis,
        "size_matches": match.size_matches,
    }


def _ambiguous_match_to_dict(ambiguous: AmbiguousMatch) -> dict[str, Any]:
    return {
        "local_document_id": ambiguous.local_document_id,
        "local_filename": ambiguous.local_filename,
        "candidate_benchmark_filenames": list(ambiguous.candidate_benchmark_filenames),
        "reason": ambiguous.reason,
    }


def _ocr_metrics_to_dict(metrics: DocumentOcrMetrics) -> dict[str, Any]:
    return {
        "document_id": metrics.document_id,
        "display_filename": metrics.display_filename,
        "artifact_availability": _availability_to_dict(metrics.artifact_availability),
        "page_count": metrics.page_count,
        "pages_good_text_layer": metrics.pages_good_text_layer,
        "pages_low_confidence_text_layer": metrics.pages_low_confidence_text_layer,
        "pages_broken_text_layer": metrics.pages_broken_text_layer,
        "pages_empty_text_layer": metrics.pages_empty_text_layer,
        "pages_needing_ocr": metrics.pages_needing_ocr,
        "pdf_broken_text_layer": metrics.pdf_broken_text_layer_flag,
        "pdf_pages_need_ocr": metrics.pdf_pages_need_ocr_flag,
        "text_source": metrics.text_source,
        "final_char_count": metrics.final_char_count,
        "final_word_count": metrics.final_word_count,
        "pages_without_text": metrics.pages_without_text,
        "ocr_pages_count": metrics.ocr_pages_count,
        "text_layer_pages_count": metrics.text_layer_pages_count,
        "ocr_pages_with_confidence": metrics.ocr_pages_with_confidence,
        "ocr_lines_with_confidence": metrics.ocr_lines_with_confidence,
        "ocr_page_confidence_mean": _rounded(metrics.ocr_page_confidence_mean),
        "ocr_page_confidence_min": _rounded(metrics.ocr_page_confidence_min),
        "ocr_page_confidence_max": _rounded(metrics.ocr_page_confidence_max),
        "quality_report_used": metrics.quality_report_used,
        "expected_pipeline_category": metrics.expected_pipeline_category,
        "actual_pipeline_category": metrics.actual_pipeline_category,
        "routing_matches_expectation": metrics.routing_matches_expectation,
        "notes": list(metrics.notes),
    }


def _rounded(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _entity_type_metrics_to_dict(metrics: EntityTypeMetrics) -> dict[str, Any]:
    return {
        "entity_type": metrics.entity_type,
        "expected_count": metrics.expected_count,
        "detected_count": metrics.detected_count,
        "tp": metrics.tp,
        "fp": metrics.fp,
        "fn": metrics.fn,
        "precision": round(metrics.precision, 4),
        "recall": round(metrics.recall, 4),
        "f1": round(metrics.f1, 4),
    }


def _pii_metrics_to_dict(metrics: DocumentPiiMetrics) -> dict[str, Any]:
    return {
        "document_id": metrics.document_id,
        "display_filename": metrics.display_filename,
        "matching_mode": metrics.matching_mode,
        "expected_candidate_count": metrics.expected_candidate_count,
        "detected_entity_count": metrics.detected_entity_count,
        "tp": metrics.tp,
        "fp": metrics.fp,
        "fn": metrics.fn,
        "precision": round(metrics.precision, 4),
        "recall": round(metrics.recall, 4),
        "f1": round(metrics.f1, 4),
        "missing_entity_types": list(metrics.missing_entity_types),
        "extra_entity_types": list(metrics.extra_entity_types),
        "unsupported_entity_types": list(metrics.unsupported_entity_types),
        "by_type": [_entity_type_metrics_to_dict(t) for t in metrics.by_type],
    }


def _global_pii_to_dict(metrics: GlobalPiiMetrics) -> dict[str, Any]:
    return {
        "total_expected": metrics.total_expected,
        "total_detected": metrics.total_detected,
        "total_tp": metrics.total_tp,
        "total_fp": metrics.total_fp,
        "total_fn": metrics.total_fn,
        "precision": round(metrics.precision, 4),
        "recall": round(metrics.recall, 4),
        "f1": round(metrics.f1, 4),
        "by_type": [_entity_type_metrics_to_dict(t) for t in metrics.by_type],
        "by_type_group": {
            group: _entity_type_metrics_to_dict(group_metrics)
            for group, group_metrics in metrics.by_type_group.items()
        },
        "unsupported_entity_types": list(metrics.unsupported_entity_types),
    }


def _validation_aggregate_to_dict(summary: ValidationBenchmarkSummary) -> dict[str, Any]:
    return {
        "documents_considered": summary.documents_considered,
        "documents_with_validation_enabled": summary.documents_with_validation_enabled,
        "total_kept": summary.total_kept,
        "total_dropped": summary.total_dropped,
        "total_score_down": summary.total_score_down,
        "dropped_by_reason": dict(summary.dropped_by_reason),
        "score_down_by_reason": dict(summary.score_down_by_reason),
    }


def _highlighted_documents(documents_section: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    highlighted: dict[str, list[dict[str, Any]]] = {}
    for entry in documents_section:
        document = entry.get("document") or {}
        filename = document.get("display_filename") or ""
        stem = filename.rsplit(".", 1)[0] if filename else ""
        for name in HIGHLIGHTED_DOCUMENT_STEMS:
            if stem == name or stem.startswith(name):
                highlighted.setdefault(name, []).append(entry)
    return highlighted


def build_report(
    *,
    generated_at: str,
    repo_commit: str | None,
    inputs: dict[str, Any],
    local_documents: Sequence[LocalDocument],
    match_result: MatchResult,
    ocr_per_document: Sequence[DocumentOcrMetrics],
    ocr_aggregate: OcrAggregateMetrics | None,
    pii_per_document: Sequence[DocumentPiiMetrics],
    global_pii: GlobalPiiMetrics | None,
    missing_artifacts: Sequence[dict[str, Any]],
    validation_aggregate: ValidationBenchmarkSummary | None = None,
) -> dict[str, Any]:
    """Build the full JSON-serializable report structure. Markdown is rendered from this."""
    documents_by_id = {doc.document_id: doc for doc in local_documents}
    ocr_by_id = {metrics.document_id: metrics for metrics in ocr_per_document}
    pii_by_id = {metrics.document_id: metrics for metrics in pii_per_document}

    documents_section: list[dict[str, Any]] = []
    for matched in match_result.matched:
        doc = documents_by_id.get(matched.document_id)
        documents_section.append(
            {
                "match": _matched_document_to_dict(matched),
                "document": _local_document_to_dict(doc) if doc else None,
                "ocr_text_metrics": (
                    _ocr_metrics_to_dict(ocr_by_id[matched.document_id])
                    if matched.document_id in ocr_by_id
                    else None
                ),
                "pii_metrics": (
                    _pii_metrics_to_dict(pii_by_id[matched.document_id])
                    if matched.document_id in pii_by_id
                    else None
                ),
            }
        )

    ocr_text_quality = None
    if ocr_aggregate is not None:
        ocr_text_quality = {
            "aggregate": {
                "total_good_text_layer_pages": ocr_aggregate.total_good_text_layer_pages,
                "total_low_confidence_text_layer_pages": (
                    ocr_aggregate.total_low_confidence_text_layer_pages
                ),
                "total_broken_text_layer_pages": ocr_aggregate.total_broken_text_layer_pages,
                "total_empty_text_layer_pages": ocr_aggregate.total_empty_text_layer_pages,
                "total_needs_ocr_pages": ocr_aggregate.total_needs_ocr_pages,
                "total_pages_without_text": ocr_aggregate.total_pages_without_text,
                "total_ocr_pages_with_confidence": (
                    ocr_aggregate.total_ocr_pages_with_confidence
                ),
                "total_ocr_lines_with_confidence": (
                    ocr_aggregate.total_ocr_lines_with_confidence
                ),
                "ocr_page_confidence_mean": _rounded(
                    ocr_aggregate.ocr_page_confidence_mean
                ),
                "ocr_page_confidence_min": _rounded(
                    ocr_aggregate.ocr_page_confidence_min
                ),
                "ocr_page_confidence_max": _rounded(
                    ocr_aggregate.ocr_page_confidence_max
                ),
            },
            "routing_mismatches": list(ocr_aggregate.routing_mismatches),
            "highlighted_documents": _highlighted_documents(documents_section),
        }

    pii_benchmark = None
    if global_pii is not None:
        pii_benchmark = {"global": _global_pii_to_dict(global_pii)}
        if validation_aggregate is not None:
            pii_benchmark["validation"] = _validation_aggregate_to_dict(validation_aggregate)

    return {
        "generated_at": generated_at,
        "repo_commit": repo_commit,
        "document_count": len(local_documents),
        "inputs": inputs,
        "corpus_coverage": {
            "matched_documents": [_matched_document_to_dict(m) for m in match_result.matched],
            "unmatched_local_documents": list(match_result.unmatched_local_documents),
            "unmatched_benchmark_entries": list(match_result.unmatched_benchmark_entries),
            "unsupported_file_type_entries": list(match_result.unsupported_file_type_entries),
            "ambiguous_matches": [
                _ambiguous_match_to_dict(a) for a in match_result.ambiguous_matches
            ],
        },
        "documents": documents_section,
        "ocr_text_quality": ocr_text_quality,
        "pii_benchmark": pii_benchmark,
        "missing_or_unsupported": {
            "unmatched_local_documents": list(match_result.unmatched_local_documents),
            "unmatched_benchmark_entries": list(match_result.unmatched_benchmark_entries),
            "unsupported_file_type_entries": list(match_result.unsupported_file_type_entries),
            "ambiguous_matches": [
                _ambiguous_match_to_dict(a) for a in match_result.ambiguous_matches
            ],
            "documents_missing_artifacts": list(missing_artifacts),
            "unsupported_entity_types": (
                list(global_pii.unsupported_entity_types) if global_pii is not None else []
            ),
        },
        "safety": {
            "raw_values_included": False,
            "note": (
                "Report contains only counts, statuses, types, and offsets. No extracted text, "
                "masked ground-truth value, or detected entity text was read into this report."
            ),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Render the markdown report from the shared report dict."""
    lines: list[str] = []
    inputs = report.get("inputs", {})
    coverage = report["corpus_coverage"]
    ocr_quality = report.get("ocr_text_quality")
    pii_benchmark = report.get("pii_benchmark")
    mou = report["missing_or_unsupported"]

    lines += [
        "# Private OCR/PII Benchmark Report",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Repo commit: {report.get('repo_commit') or 'unknown'}",
        f"- Document count: {report['document_count']}",
        "- Artifact coverage: "
        f"metadata={'present' if inputs.get('metadata_present') else 'missing'}, "
        f"groundtruth={'present' if inputs.get('groundtruth_present') else 'missing'}",
        "",
        "## Executive Summary",
        "",
        f"- Matched documents: {len(coverage['matched_documents'])}",
        f"- Unmatched local documents: {len(coverage['unmatched_local_documents'])}",
        f"- Unmatched benchmark entries: {len(coverage['unmatched_benchmark_entries'])}",
        f"- Unsupported file types (e.g. .txt): {len(coverage['unsupported_file_type_entries'])}",
        f"- Ambiguous matches: {len(coverage['ambiguous_matches'])}",
        f"- Documents missing one or more artifacts: {len(mou['documents_missing_artifacts'])}",
    ]
    if ocr_quality:
        mismatches = ocr_quality["routing_mismatches"]
        lines.append(f"- OCR/text routing mismatches vs. benchmark expectation: {len(mismatches)}")
        if mismatches:
            lines.append(f"  - {', '.join(mismatches)}")
    if pii_benchmark:
        g = pii_benchmark["global"]
        lines.append(
            f"- PII vs. candidate ground truth: precision={g['precision']}, recall={g['recall']}, "
            f"f1={g['f1']} (tp={g['total_tp']}, fp={g['total_fp']}, fn={g['total_fn']})"
        )
        if g["unsupported_entity_types"]:
            lines.append(
                f"  - Unsupported entity types: {', '.join(g['unsupported_entity_types'])}"
            )
    lines.append("")

    lines += [
        "## Corpus Coverage",
        "",
        "| Document ID | Local filename | Benchmark filename | Match basis | Size matches |",
        "|---|---|---|---|---|",
    ]
    for m in coverage["matched_documents"]:
        lines.append(
            f"| `{m['document_id']}` | {m['local_filename']} | {m['benchmark_filename']} | "
            f"{m['match_basis']} | {m['size_matches']} |"
        )
    lines.append("")

    lines.append("## OCR/Text Quality")
    lines.append("")
    if ocr_quality:
        lines += [
            "| Document | Pages | Good | Low conf. | Broken | Empty | Needs OCR | No text | "
            "OCR conf. | Text source | Expected pipeline | Actual pipeline | Routing match |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|",
        ]
        for entry in report["documents"]:
            ocr = entry.get("ocr_text_metrics")
            if not ocr:
                continue
            lines.append(
                f"| {ocr['display_filename']} | {ocr['page_count']} | "
                f"{ocr['pages_good_text_layer']} | {ocr['pages_low_confidence_text_layer']} | "
                f"{ocr['pages_broken_text_layer']} | {ocr['pages_empty_text_layer']} | "
                f"{ocr['pages_needing_ocr']} | {ocr['pages_without_text']} | "
                f"{ocr['ocr_page_confidence_mean']} | "
                f"{ocr['text_source']} | "
                f"{ocr['expected_pipeline_category']} | {ocr['actual_pipeline_category']} | "
                f"{ocr['routing_matches_expectation']} |"
            )
        agg = ocr_quality["aggregate"]
        lines += [
            "",
            "Aggregated page status counts:",
            "",
            f"- GOOD_TEXT_LAYER: {agg['total_good_text_layer_pages']}",
            f"- LOW_CONFIDENCE_TEXT_LAYER: {agg['total_low_confidence_text_layer_pages']}",
            f"- BROKEN_TEXT_LAYER: {agg['total_broken_text_layer_pages']}",
            f"- EMPTY_TEXT_LAYER: {agg['total_empty_text_layer_pages']}",
            f"- needs_ocr pages: {agg['total_needs_ocr_pages']}",
            f"- pages without final text: {agg['total_pages_without_text']}",
            f"- OCR pages with confidence: {agg['total_ocr_pages_with_confidence']}",
            f"- OCR lines with confidence: {agg['total_ocr_lines_with_confidence']}",
            f"- OCR page confidence mean/min/max: {agg['ocr_page_confidence_mean']} / "
            f"{agg['ocr_page_confidence_min']} / {agg['ocr_page_confidence_max']}",
            "",
        ]
        highlighted = ocr_quality.get("highlighted_documents") or {}
        if highlighted:
            lines.append("Highlighted documents:")
            lines.append("")
            for name, entries in highlighted.items():
                for entry in entries:
                    ocr = entry["ocr_text_metrics"]
                    lines.append(
                        f"- **{name}** (`{ocr['display_filename']}`): "
                        f"needs_ocr={ocr['pages_needing_ocr']}/{ocr['page_count']}, "
                        f"broken={ocr['pages_broken_text_layer']}, "
                        f"empty={ocr['pages_empty_text_layer']}, "
                        f"routing_match={ocr['routing_matches_expectation']}"
                    )
            lines.append("")
    else:
        lines.append("_OCR/text metrics skipped (`--no-ocr`)._")
        lines.append("")

    lines.append("## PII Benchmark")
    lines.append("")
    if pii_benchmark:
        lines += [
            "| Document | Expected | Detected | TP | FP | FN | Precision | Recall | F1 | Mode |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for entry in report["documents"]:
            pii = entry.get("pii_metrics")
            if not pii:
                continue
            lines.append(
                f"| {pii['display_filename']} | {pii['expected_candidate_count']} | "
                f"{pii['detected_entity_count']} | {pii['tp']} | {pii['fp']} | {pii['fn']} | "
                f"{pii['precision']} | {pii['recall']} | {pii['f1']} | {pii['matching_mode']} |"
            )
        lines += [
            "",
            "Per entity type (corpus-wide):",
            "",
            "| Entity type | Expected | Detected | TP | FP | FN | Precision | Recall | F1 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for t in pii_benchmark["global"]["by_type"]:
            lines.append(
                f"| {t['entity_type']} | {t['expected_count']} | {t['detected_count']} | "
                f"{t['tp']} | {t['fp']} | {t['fn']} | {t['precision']} | {t['recall']} | "
                f"{t['f1']} |"
            )
        lines += [
            "",
            "Per type group:",
            "",
            "| Group | Expected | Detected | TP | FP | FN | Precision | Recall | F1 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for group, t in pii_benchmark["global"]["by_type_group"].items():
            lines.append(
                f"| {group} | {t['expected_count']} | {t['detected_count']} | {t['tp']} | "
                f"{t['fp']} | {t['fn']} | {t['precision']} | {t['recall']} | {t['f1']} |"
            )
        g = pii_benchmark["global"]
        lines += [
            "",
            f"**Global**: expected={g['total_expected']}, detected={g['total_detected']}, "
            f"tp={g['total_tp']}, fp={g['total_fp']}, fn={g['total_fn']}, "
            f"precision={g['precision']}, recall={g['recall']}, f1={g['f1']}",
            "",
        ]
        validation = pii_benchmark.get("validation")
        if validation:
            lines += [
                "### Candidate Validation (Engine-5)",
                "",
                f"- Documents considered: {validation['documents_considered']} "
                f"({validation['documents_with_validation_enabled']} with validation enabled)",
                f"- Kept: {validation['total_kept']}, dropped: {validation['total_dropped']}, "
                f"score_down: {validation['total_score_down']}",
            ]
            if validation["dropped_by_reason"]:
                lines.append(f"- Dropped by reason: {validation['dropped_by_reason']}")
            if validation["score_down_by_reason"]:
                lines.append(f"- Score-down by reason: {validation['score_down_by_reason']}")
            lines.append("")
    else:
        lines.append("_PII metrics skipped (`--no-pii`)._")
        lines.append("")

    lines.append("## Missing / Unsupported")
    lines.append("")
    any_missing = False
    if mou["unmatched_local_documents"]:
        any_missing = True
        lines.append(f"- Unmatched local documents: {', '.join(mou['unmatched_local_documents'])}")
    if mou["unmatched_benchmark_entries"]:
        any_missing = True
        lines.append(
            f"- Unmatched benchmark entries: {', '.join(mou['unmatched_benchmark_entries'])}"
        )
    if mou["unsupported_file_type_entries"]:
        any_missing = True
        lines.append(
            f"- Unsupported file types: {', '.join(mou['unsupported_file_type_entries'])}"
        )
    if mou["ambiguous_matches"]:
        any_missing = True
        lines.append(f"- Ambiguous matches: {len(mou['ambiguous_matches'])} (see JSON report)")
    if mou["documents_missing_artifacts"]:
        any_missing = True
        lines.append("- Documents missing artifacts:")
        for item in mou["documents_missing_artifacts"]:
            lines.append(
                f"  - `{item['document_id']}` ({item.get('display_filename')}): "
                f"missing {', '.join(item['missing'])}"
            )
    if mou["unsupported_entity_types"]:
        any_missing = True
        lines.append(
            "- Entity types unsupported by the current pipeline: "
            f"{', '.join(mou['unsupported_entity_types'])}"
        )
    if not any_missing:
        lines.append("_Nothing to report._")
    lines.append("")

    lines += [
        "## Safety",
        "",
        f"- {report['safety']['note']}",
        "- Confirmed: no raw text, masked value, or entity text field was serialized into this "
        "report (see `privacy_guard.py`, enforced before write).",
        "",
    ]

    return "\n".join(lines)
