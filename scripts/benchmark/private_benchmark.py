#!/usr/bin/env python3
"""Private local OCR/PII benchmark runner (PR B).

Reads already-computed audit/OCR/PII artifacts from ``--document-data-dir`` and private
benchmark inputs (metadata + candidate PII ground truth) from local JSON files, matches them to
the local corpus, and writes a safe markdown+JSON report. Never triggers OCR/PII processing,
never calls the API, never writes or deletes a document. See ``README.md`` in this directory.

Usage:
    python scripts/benchmark/private_benchmark.py \\
        --uploads-dir volumes/uploads \\
        --document-data-dir volumes/document-data \\
        --metadata volumes/benchmark/ocr_pii_benchmark_metadata.json \\
        --groundtruth volumes/benchmark/ocr_pii_benchmark_pii_groundtruth.json \\
        --output-dir volumes/benchmark/reports
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from artifact_loader import DocumentArtifacts, load_local_corpus  # noqa: E402
from document_matching import (  # noqa: E402
    LocalDocRef,
    load_benchmark_metadata,
    load_groundtruth,
    match_documents,
)
from ocr_metrics import aggregate_ocr_metrics, compute_document_ocr_metrics  # noqa: E402
from pii_matching import (  # noqa: E402
    aggregate_validation_summaries,
    build_document_pii_metrics,
    build_global_pii_metrics,
)
from privacy_guard import PrivacyGuardError, assert_report_is_safe, assert_text_is_safe  # noqa: E402
from report_builder import build_report, render_markdown  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uploads-dir", default="volumes/uploads", type=Path)
    parser.add_argument("--document-data-dir", default="volumes/document-data", type=Path)
    parser.add_argument(
        "--metadata", default="volumes/benchmark/ocr_pii_benchmark_metadata.json", type=Path
    )
    parser.add_argument(
        "--groundtruth",
        default="volumes/benchmark/ocr_pii_benchmark_pii_groundtruth.json",
        type=Path,
    )
    parser.add_argument("--output-dir", default="volumes/benchmark/reports", type=Path)
    parser.add_argument(
        "--fail-on-missing-input",
        action="store_true",
        help="Exit non-zero if the metadata or ground-truth input file is missing.",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--json-only", action="store_true")
    output_group.add_argument("--markdown-only", action="store_true")
    parser.add_argument("--no-pii", action="store_true", help="Skip PII benchmark metrics.")
    parser.add_argument("--no-ocr", action="store_true", help="Skip OCR/text quality metrics.")
    return parser.parse_args(argv)


def _repo_commit() -> str | None:
    """Best-effort short commit hash. Falls back to reading ``.git/HEAD`` directly so this still
    works in a minimal container image (e.g. ``python:3.12-slim``) that has no ``git`` binary."""
    commit = _repo_commit_via_git_cli()
    return commit if commit is not None else _repo_commit_via_git_dir()


def _repo_commit_via_git_cli() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _repo_commit_via_git_dir() -> str | None:
    git_dir = _REPO_ROOT / ".git"
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not head.startswith("ref:"):
        return head[:8] or None

    ref = head.split(" ", 1)[1].strip()
    try:
        sha = (git_dir / ref).read_text(encoding="utf-8").strip()
        return sha[:8] or None
    except OSError:
        pass

    try:
        for line in (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(f" {ref}"):
                return line.split(" ", 1)[0][:8] or None
    except OSError:
        return None
    return None


def _missing_artifacts(local_artifacts: list[DocumentArtifacts]) -> list[dict[str, Any]]:
    entries = []
    for artifacts in local_artifacts:
        missing = [
            kind
            for kind, value in (
                ("audit_result", artifacts.audit),
                ("text_result", artifacts.text),
                ("pii_result", artifacts.pii),
            )
            if value is None
        ]
        if missing:
            entries.append(
                {
                    "document_id": artifacts.document.document_id,
                    "display_filename": artifacts.document.display_filename,
                    "missing": missing,
                }
            )
    return entries


def run(args: argparse.Namespace) -> dict[str, Any]:
    metadata_present = args.metadata.is_file()
    groundtruth_present = args.groundtruth.is_file()

    local_artifacts = load_local_corpus(args.uploads_dir, args.document_data_dir)
    metadata_entries = load_benchmark_metadata(args.metadata) if metadata_present else []
    groundtruth_docs = load_groundtruth(args.groundtruth) if groundtruth_present else []

    metadata_by_filename = {entry.filename: entry for entry in metadata_entries}
    groundtruth_by_filename = {doc.filename: doc for doc in groundtruth_docs}

    benchmark_sizes: dict[str, int | None] = {}
    for entry in metadata_entries:
        benchmark_sizes[entry.filename] = entry.size_bytes
    for doc in groundtruth_docs:
        benchmark_sizes.setdefault(doc.filename, doc.file_size)

    local_refs = [
        LocalDocRef(
            document_id=artifacts.document.document_id,
            filename=artifacts.document.display_filename,
            size_bytes=artifacts.document.size_bytes,
        )
        for artifacts in local_artifacts
    ]
    match_result = match_documents(local_refs, list(benchmark_sizes.items()))
    artifacts_by_id = {artifacts.document.document_id: artifacts for artifacts in local_artifacts}

    ocr_per_document = []
    ocr_aggregate = None
    if not args.no_ocr:
        for matched in match_result.matched:
            artifacts = artifacts_by_id[matched.document_id]
            benchmark_entry = metadata_by_filename.get(matched.benchmark_filename)
            ocr_per_document.append(
                compute_document_ocr_metrics(
                    matched.document_id, matched.local_filename, artifacts, benchmark_entry
                )
            )
        ocr_aggregate = aggregate_ocr_metrics(ocr_per_document)

    pii_per_document = []
    global_pii = None
    validation_aggregate = None
    if not args.no_pii:
        for matched in match_result.matched:
            groundtruth_doc = groundtruth_by_filename.get(matched.benchmark_filename)
            if groundtruth_doc is None:
                continue
            artifacts = artifacts_by_id[matched.document_id]
            detected_entities = artifacts.pii.entities if artifacts.pii else ()
            configured_types = artifacts.pii.configured_entity_types if artifacts.pii else ()
            matching_mode = (
                "page_aware" if artifacts.text is not None and artifacts.text.pages else "document_level"
            )
            pii_per_document.append(
                build_document_pii_metrics(
                    matched.document_id,
                    matched.local_filename,
                    detected_entities,
                    configured_types,
                    groundtruth_doc.entities,
                    matching_mode,
                )
            )
        global_pii = build_global_pii_metrics(pii_per_document)
        # Independent of ground truth: every matched document with a pii_result contributes its
        # Engine-5 candidate-validation summary, whether or not it also has benchmark ground truth.
        validation_aggregate = aggregate_validation_summaries(
            artifacts_by_id[matched.document_id].pii.validation
            for matched in match_result.matched
            if artifacts_by_id[matched.document_id].pii is not None
        )

    inputs = {
        "uploads_dir": str(args.uploads_dir),
        "document_data_dir": str(args.document_data_dir),
        "metadata_path": str(args.metadata),
        "groundtruth_path": str(args.groundtruth),
        "metadata_present": metadata_present,
        "groundtruth_present": groundtruth_present,
        "pii_enabled": not args.no_pii,
        "ocr_enabled": not args.no_ocr,
    }

    report: dict[str, Any] = build_report(
        generated_at=datetime.now(UTC).isoformat(),
        repo_commit=_repo_commit(),
        inputs=inputs,
        local_documents=[artifacts.document for artifacts in local_artifacts],
        match_result=match_result,
        ocr_per_document=ocr_per_document,
        ocr_aggregate=ocr_aggregate,
        pii_per_document=pii_per_document,
        global_pii=global_pii,
        validation_aggregate=validation_aggregate,
        missing_artifacts=_missing_artifacts(local_artifacts),
    )
    return report


def _write_summary_csv(path: Path, report: dict[str, Any]) -> None:
    fieldnames = [
        "document_id",
        "display_filename",
        "page_count",
        "pages_needing_ocr",
        "ocr_pages_with_confidence",
        "ocr_page_confidence_mean",
        "text_source",
        "expected_pipeline_category",
        "actual_pipeline_category",
        "routing_matches_expectation",
        "pii_expected",
        "pii_detected",
        "pii_tp",
        "pii_fp",
        "pii_fn",
        "pii_precision",
        "pii_recall",
        "pii_f1",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for entry in report["documents"]:
            ocr = entry.get("ocr_text_metrics") or {}
            pii = entry.get("pii_metrics") or {}
            document = entry.get("document") or {}
            writer.writerow(
                {
                    "document_id": entry["match"]["document_id"],
                    "display_filename": document.get("display_filename"),
                    "page_count": ocr.get("page_count"),
                    "pages_needing_ocr": ocr.get("pages_needing_ocr"),
                    "ocr_pages_with_confidence": ocr.get("ocr_pages_with_confidence"),
                    "ocr_page_confidence_mean": ocr.get("ocr_page_confidence_mean"),
                    "text_source": ocr.get("text_source"),
                    "expected_pipeline_category": ocr.get("expected_pipeline_category"),
                    "actual_pipeline_category": ocr.get("actual_pipeline_category"),
                    "routing_matches_expectation": ocr.get("routing_matches_expectation"),
                    "pii_expected": pii.get("expected_candidate_count"),
                    "pii_detected": pii.get("detected_entity_count"),
                    "pii_tp": pii.get("tp"),
                    "pii_fp": pii.get("fp"),
                    "pii_fn": pii.get("fn"),
                    "pii_precision": pii.get("precision"),
                    "pii_recall": pii.get("recall"),
                    "pii_f1": pii.get("f1"),
                }
            )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.fail_on_missing_input and not (args.metadata.is_file() and args.groundtruth.is_file()):
        print(
            "FAIL: --fail-on-missing-input set and metadata or ground-truth input is missing "
            f"(metadata={args.metadata}, groundtruth={args.groundtruth}).",
            file=sys.stderr,
        )
        return 1

    report = run(args)

    try:
        assert_report_is_safe(report)
        markdown = render_markdown(report)
        assert_text_is_safe(markdown)
    except PrivacyGuardError as exc:
        print(f"FAIL: privacy guard blocked report generation: {exc}", file=sys.stderr)
        return 2

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    written = []
    if not args.markdown_only:
        json_path = output_dir / "benchmark_report.json"
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(json_path)
    if not args.json_only:
        md_path = output_dir / "benchmark_report.md"
        md_path.write_text(markdown, encoding="utf-8")
        written.append(md_path)
        csv_path = output_dir / "benchmark_summary.csv"
        _write_summary_csv(csv_path, report)
        written.append(csv_path)

    coverage = report["corpus_coverage"]
    print(f"Report written to: {output_dir}")
    for path in written:
        print(f"  - {path.name}")
    print(f"Matched documents: {len(coverage['matched_documents'])}")
    print(f"Unmatched local documents: {len(coverage['unmatched_local_documents'])}")
    print(f"Unmatched benchmark entries: {len(coverage['unmatched_benchmark_entries'])}")
    print(f"Ambiguous matches: {len(coverage['ambiguous_matches'])}")
    print(f"Documents missing artifacts: {len(report['missing_or_unsupported']['documents_missing_artifacts'])}")
    if report.get("pii_benchmark"):
        g = report["pii_benchmark"]["global"]
        print(
            "PII (candidate ground truth): "
            f"expected={g['total_expected']} detected={g['total_detected']} "
            f"tp={g['total_tp']} fp={g['total_fp']} fn={g['total_fn']} "
            f"precision={g['precision']} recall={g['recall']} f1={g['f1']}"
        )
        validation = report["pii_benchmark"].get("validation")
        if validation:
            print(
                "PII candidate validation: "
                f"kept={validation['total_kept']} dropped={validation['total_dropped']} "
                f"score_down={validation['total_score_down']} "
                f"(documents={validation['documents_considered']}, "
                f"validation_enabled={validation['documents_with_validation_enabled']})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
