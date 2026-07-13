"""Aggregate the dev review-feedback channel into an error-taxonomy + consistency report.

The Review UI has two channels. The **binding decision** (keep/false_positive/pseudonymize) +
manual additions build the gold GT (see ``harvest_groundtruth.py``). The **dev feedback**
("Problem auswählen" → ``feedback/pii_feedback.jsonl``) is a diagnostic side-channel: per entity a
verdict (``positive``/``issue``) and an issue type (``span_too_long_right``, ``false_positive``,
``wrong_type``, ``overlap_conflict``, ``duplicate_or_should_merge``, ``missing_related_entity``, …).
This tool turns that channel into *which errors actually occur, how often, and where* — the signal
that prioritizes fixes.

Tolerant of reviewer mistakes by design: the feedback log is append-only, so a reviewer can revise a
verdict; this reads the **latest verdict per entity** (a mind-change wins) and additionally surfaces
entities whose verdict *changed* over time, so a slip can be re-checked rather than trusted blindly.

Privacy: reads only ids, types, offsets, recognizers, verdicts, and issue codes. It never emits the
free-text ``comment`` (only whether one exists) and no document text.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        return []
    return [r for r in records if isinstance(r, dict)]


def _entity_key(record: dict) -> tuple[str, str, int, int, str]:
    entity = record.get("entity") or {}
    return (
        str(record.get("document_id")),
        str(entity.get("type")),
        int(entity.get("start", -1)),
        int(entity.get("end", -1)),
        str(entity.get("recognizer")),
    )


def _latest_per_entity(records: Sequence[dict]) -> tuple[dict[tuple, dict], list[tuple]]:
    """Collapse append-only feedback to the latest record per entity (a revision wins).

    Returns the latest-per-entity map and the keys whose verdict changed over time (mind-changes to
    re-check — reviewer slips are expected and fine).
    """
    by_entity: dict[tuple, list[dict]] = defaultdict(list)
    for record in records:
        by_entity[_entity_key(record)].append(record)
    latest: dict[tuple, dict] = {}
    changed: list[tuple] = []
    for key, group in by_entity.items():
        ordered = sorted(group, key=lambda r: str(r.get("recorded_at") or ""))
        latest[key] = ordered[-1]
        verdicts = {str((r.get("feedback") or {}).get("verdict")) for r in ordered}
        issues = {str((r.get("feedback") or {}).get("issue_type")) for r in ordered}
        if len(verdicts) > 1 or len(issues) > 1:
            changed.append(key)
    return latest, changed


def build_feedback_report(records: Sequence[dict]) -> dict[str, object]:
    """Build the text-free error-taxonomy + consistency report from raw feedback records."""
    latest, changed = _latest_per_entity(records)

    verdicts: Counter[str] = Counter()
    issues: Counter[str] = Counter()
    by_entity_type: Counter[str] = Counter()
    issue_by_recognizer: Counter[tuple[str, str]] = Counter()
    total_by_recognizer: Counter[str] = Counter()
    documents: set[str] = set()
    comments = 0

    for key, record in latest.items():
        feedback = record.get("feedback") or {}
        entity = record.get("entity") or {}
        verdict = str(feedback.get("verdict"))
        issue = str(feedback.get("issue_type"))
        recognizer = str(entity.get("recognizer"))
        verdicts[verdict] += 1
        by_entity_type[str(entity.get("type"))] += 1
        total_by_recognizer[recognizer] += 1
        documents.add(key[0])
        if (feedback.get("comment") or "").strip():
            comments += 1
        # "correct" is the positive marker; everything else is a concrete problem class.
        if verdict == "issue" or (issue and issue != "correct"):
            issues[issue] += 1
            issue_by_recognizer[(recognizer, issue)] += 1

    # Systematic vs. isolated: recognizers with the highest issue share are likely detector problems
    # to fix; a single isolated issue is more likely a one-off (detector or reviewer slip).
    recognizer_issue_rate = []
    per_recognizer_issues: Counter[str] = Counter()
    for (recognizer, _issue), count in issue_by_recognizer.items():
        per_recognizer_issues[recognizer] += count
    for recognizer, issue_count in per_recognizer_issues.items():
        total = total_by_recognizer[recognizer]
        recognizer_issue_rate.append(
            {
                "recognizer": recognizer,
                "issues": issue_count,
                "total": total,
                "issue_rate": round(issue_count / total, 3) if total else 0.0,
            }
        )
    recognizer_issue_rate.sort(key=lambda r: (-r["issues"], -r["issue_rate"], r["recognizer"]))

    return {
        "entities_with_feedback": len(latest),
        "documents": len(documents),
        "comments_present": comments,
        "verdicts": dict(verdicts.most_common()),
        "issue_types_sorted": [
            {"issue_type": issue, "count": count} for issue, count in issues.most_common()
        ],
        "by_entity_type": dict(by_entity_type.most_common()),
        "recognizer_issue_rate": recognizer_issue_rate,
        "revised_entities": len(changed),
    }


def build_report_from_store(document_data_dir: Path) -> dict[str, object]:
    records: list[dict] = []
    if document_data_dir.is_dir():
        for doc_dir in sorted(p for p in document_data_dir.iterdir() if p.is_dir()):
            records.extend(_read_jsonl(doc_dir / "feedback" / "pii_feedback.jsonl"))
    return build_feedback_report(records)


def _print_summary(report: dict[str, object]) -> None:
    print(
        f"Feedback: {report['entities_with_feedback']} entities across "
        f"{report['documents']} documents ({report['comments_present']} with a comment, "
        f"{report['revised_entities']} revised)."
    )
    print(f"  verdicts: {report['verdicts']}")
    issues = report["issue_types_sorted"]
    assert isinstance(issues, list)
    if issues:
        print("  problems (most frequent first):")
        for item in issues:
            print(f"    {item['count']:3d}x  {item['issue_type']}")
    rates = report["recognizer_issue_rate"]
    assert isinstance(rates, list)
    if rates:
        print("  recognizers with issues (fix candidates):")
        for item in rates[:8]:
            print(f"    {item['issues']:3d}/{item['total']:<3d} ({item['issue_rate']})  {item['recognizer']}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate dev review feedback into a report.")
    parser.add_argument("--document-data-dir", type=Path, default=Path("volumes/document-store"))
    parser.add_argument("--out", type=Path, default=None, help="Optional JSON report output path.")
    args = parser.parse_args(argv)

    report = build_report_from_store(args.document_data_dir)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote feedback report: {args.out}")
    _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
