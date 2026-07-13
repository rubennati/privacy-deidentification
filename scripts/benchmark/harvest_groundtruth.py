"""Harvest a GOLD ground truth from persisted review decisions (Weg B step 2).

A reviewer's binding decisions (`keep` / `false_positive` / `pseudonymize`) and manual additions —
made in the Review UI and snapshotted as an immutable `pii_review_result` artifact after every
decision — are the human truth signal. This turns the latest snapshot per document into the
benchmark's gold ground truth: confirmed detections (`accepted`/`kept`) plus accepted manual
additions, minus `rejected` false positives.

Unlike the *proposal* exporter (`build_groundtruth_proposal.py`, which just dumps raw detections),
this reflects real human judgement. It also folds in the **dev-feedback channel**: an entity a
reviewer marked ``correct`` ("Passt") becomes a confirmed anchor even without a binding decision, so
a document reviewed only via that channel is not lost. The binding decision wins where both exist;
an ``issue`` verdict is never harvested as truth (it flags a problem — see `analyze_feedback.py`).

It is offset-only and **reads no document text**: the review snapshot is text-free by construction,
and the referenced text artifact is read only for its per-page character counts, used to map the
global raw offsets onto the page-local coordinates the benchmark matcher compares (the same
`len(page) + 2` join the pipeline uses to build the combined raw text). Output belongs under the
git-ignored `volumes/` tree.

Caveat: a detection kept at its detected boundary bakes that boundary into the GT. For boundary-exact
gold GT, an over-capture should be rejected + re-added at the correct span (or flagged via dev
feedback), not merely kept — see the benchmark README.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

# Confirmed-PII statuses harvested into the gold GT; "rejected" (a false positive) is excluded.
_CONFIRMED_STATUSES = frozenset({"accepted", "kept"})


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _latest_snapshot(artifacts_dir: Path) -> dict | None:
    """The newest ``pii_review_result`` artifact in a document's artifacts dir (by ``created_at``)."""
    if not artifacts_dir.is_dir():
        return None
    best: dict | None = None
    best_created = ""
    for path in artifacts_dir.glob("*.json"):
        data = _read_json(path)
        if data is None or data.get("artifact_type") != "pii_review_result":
            continue
        created = str(data.get("created_at") or "")
        if best is None or created > best_created:
            best, best_created = data, created
    return best


def _latest_text_result(artifacts_dir: Path) -> dict | None:
    """The newest ``text_result`` artifact — used to map feedback offsets on docs with no snapshot."""
    if not artifacts_dir.is_dir():
        return None
    best: dict | None = None
    best_created = ""
    for path in artifacts_dir.glob("*.json"):
        data = _read_json(path)
        if data is None or data.get("artifact_type") != "text_result":
            continue
        created = str(data.get("created_at") or "")
        if best is None or created > best_created:
            best, best_created = data, created
    return best


def _read_jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _latest_feedback_per_entity(records: list[dict]) -> list[dict]:
    """Collapse the append-only dev-feedback log to the latest record per entity (a revision wins)."""
    latest: dict[tuple, dict] = {}
    for record in records:
        entity = record.get("entity") or {}
        key = (
            str(entity.get("type")),
            entity.get("start"),
            entity.get("end"),
            str(entity.get("recognizer")),
        )
        prev = latest.get(key)
        if prev is None or str(record.get("recorded_at") or "") >= str(prev.get("recorded_at") or ""):
            latest[key] = record
    return list(latest.values())


def _page_char_counts(text_artifact: dict) -> list[int]:
    pages = (text_artifact.get("content") or {}).get("pages") or []
    return [int(page.get("text_char_count", 0)) for page in pages]


def _page_bases(page_char_counts: Sequence[int]) -> list[tuple[int, int, int]]:
    """``(page_number, base_offset, char_count)`` per page. Pages join with a 2-char separator."""
    bases: list[tuple[int, int, int]] = []
    base = 0
    for index, count in enumerate(page_char_counts):
        bases.append((index + 1, base, count))
        base += count + 2
    return bases


def _to_page_local(
    start: int, end: int, bases: Sequence[tuple[int, int, int]]
) -> tuple[int, int, int] | None:
    """Map a global raw span to ``(page, page_local_start, page_local_end)``; None if it is out of
    range or crosses a page boundary (never guessed)."""
    for page_number, base, count in bases:
        if base <= start and end <= base + count:
            return page_number, start - base, end - base
    return None


def harvest_document(
    snapshot: dict, text_artifact: dict
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Resolve one document's snapshot into gold GT anchors (page-local) plus harvest stats."""
    content = snapshot.get("content") or {}
    bases = _page_bases(_page_char_counts(text_artifact))
    anchors: list[dict[str, object]] = []
    stats = {
        "confirmed": 0,
        "rejected": 0,
        "unmapped": 0,
        "manual_confirmed": 0,
        "manual_skipped": 0,
    }

    for occurrence in content.get("occurrences") or []:
        status = occurrence.get("review_status")
        if status == "rejected":
            stats["rejected"] += 1
            continue
        if status not in _CONFIRMED_STATUSES:
            continue
        mapped = _to_page_local(int(occurrence["raw_start"]), int(occurrence["raw_end"]), bases)
        if mapped is None:
            stats["unmapped"] += 1
            continue
        page, start, end = mapped
        anchors.append(
            {
                "entity_type": occurrence["entity_type"],
                "page": page,
                "start": start,
                "end": end,
                "origin": "detected",
                "review_status": status,
            }
        )
        stats["confirmed"] += 1

    for addition in content.get("manual_additions") or []:
        if addition.get("artifact_currency") == "stale" or addition.get("review_status") == "rejected":
            stats["manual_skipped"] += 1
            continue
        raw_start, raw_end = addition.get("raw_start"), addition.get("raw_end")
        if raw_start is None or raw_end is None or addition.get("raw_projection_status") == "unmapped":
            stats["manual_skipped"] += 1
            continue
        mapped = _to_page_local(int(raw_start), int(raw_end), bases)
        if mapped is None:
            stats["manual_skipped"] += 1
            continue
        page, start, end = mapped
        anchors.append(
            {
                "entity_type": addition["entity_type"],
                "page": page,
                "start": start,
                "end": end,
                "origin": "manual",
                "review_status": addition.get("review_status", "accepted"),
            }
        )
        stats["manual_confirmed"] += 1

    return anchors, stats


def harvest_feedback_anchors(
    feedback_records: list[dict],
    text_artifact: dict,
    covered: set[tuple[str, int, int]],
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Confirmed anchors from the dev-feedback channel: entities the reviewer marked ``correct``.

    Only a positive/``correct`` verdict becomes an anchor — it means "this detection is right as-is".
    An ``issue`` verdict (wrong boundary/type, false positive) is deliberately NOT harvested here (it
    flags a problem, not a confirmed truth; ``analyze_feedback.py`` reports those). ``covered`` holds
    ``(type, raw_start, raw_end)`` already taken from the binding-decision channel, which wins.
    """
    bases = _page_bases(_page_char_counts(text_artifact))
    anchors: list[dict[str, object]] = []
    stats = {"feedback_confirmed": 0, "feedback_unmapped": 0, "feedback_duplicate": 0}
    for record in _latest_feedback_per_entity(feedback_records):
        feedback = record.get("feedback") or {}
        entity = record.get("entity") or {}
        if feedback.get("verdict") != "positive" or feedback.get("issue_type") != "correct":
            continue
        entity_type = str(entity.get("type"))
        raw_start, raw_end = entity.get("start"), entity.get("end")
        if raw_start is None or raw_end is None:
            stats["feedback_unmapped"] += 1
            continue
        if (entity_type, int(raw_start), int(raw_end)) in covered:
            stats["feedback_duplicate"] += 1
            continue
        mapped = _to_page_local(int(raw_start), int(raw_end), bases)
        if mapped is None:
            stats["feedback_unmapped"] += 1
            continue
        page, start, end = mapped
        anchors.append(
            {
                "entity_type": entity_type,
                "page": page,
                "start": start,
                "end": end,
                "origin": "feedback",
                "review_status": "accepted",
            }
        )
        stats["feedback_confirmed"] += 1
    return anchors, stats


def build_groundtruth(
    document_data_dir: Path, *, filenames: Sequence[str] | None = None
) -> dict[str, object]:
    """Harvest gold GT from every reviewed document under ``document_data_dir``."""
    wanted = set(filenames) if filenames else None
    documents: list[dict[str, object]] = []
    skipped_no_review: list[str] = []
    if not document_data_dir.is_dir():
        return _wrap([], skipped_no_review)

    for doc_dir in sorted(p for p in document_data_dir.iterdir() if p.is_dir()):
        document_json = _read_json(doc_dir / "document.json")
        if document_json is None:
            continue
        filename = document_json.get("filename")
        if filename is None or (wanted is not None and filename not in wanted):
            continue
        artifacts_dir = doc_dir / "artifacts"
        snapshot = _latest_snapshot(artifacts_dir)
        feedback_records = _read_jsonl(doc_dir / "feedback" / "pii_feedback.jsonl")

        # Prefer the snapshot's exact text artifact; fall back to the latest text_result for a
        # feedback-only document (reviewed via the dev channel, no binding decision recorded).
        text_id = snapshot.get("input_text_artifact_id") if snapshot else None
        text_artifact = _read_json(artifacts_dir / f"{text_id}.json") if text_id else None
        if text_artifact is None:
            text_artifact = _latest_text_result(artifacts_dir)
        if text_artifact is None or (snapshot is None and not feedback_records):
            skipped_no_review.append(str(filename))
            continue

        anchors: list[dict[str, object]] = []
        stats: dict[str, int] = {}
        covered: set[tuple[str, int, int]] = set()
        if snapshot is not None:
            anchors, stats = harvest_document(snapshot, text_artifact)
            covered = _covered_spans(snapshot)
        if feedback_records:
            feedback_anchors, feedback_stats = harvest_feedback_anchors(
                feedback_records, text_artifact, covered
            )
            anchors = [*anchors, *feedback_anchors]
            stats = {**stats, **feedback_stats}

        by_type: dict[str, int] = {}
        for anchor in anchors:
            entity_type = str(anchor["entity_type"])
            by_type[entity_type] = by_type.get(entity_type, 0) + 1
        documents.append(
            {
                "filename": filename,
                "document_id": document_json.get("id"),
                "pages_count": len(_page_char_counts(text_artifact)),
                "review_snapshot_id": snapshot.get("id") if snapshot else None,
                "harvest_stats": stats,
                "entities": anchors,
                "totals": {"entity_count": len(anchors), "by_type": dict(sorted(by_type.items()))},
            }
        )
    return _wrap(documents, skipped_no_review)


def _covered_spans(snapshot: dict) -> set[tuple[str, int, int]]:
    """``(type, raw_start, raw_end)`` already taken from the binding-decision channel (wins over
    feedback). Confirmed occurrences plus mapped manual additions."""
    content = snapshot.get("content") or {}
    covered: set[tuple[str, int, int]] = set()
    for occurrence in content.get("occurrences") or []:
        if occurrence.get("review_status") in _CONFIRMED_STATUSES:
            covered.add(
                (str(occurrence["entity_type"]), int(occurrence["raw_start"]), int(occurrence["raw_end"]))
            )
    for addition in content.get("manual_additions") or []:
        if addition.get("raw_start") is not None and addition.get("raw_end") is not None:
            covered.add(
                (str(addition["entity_type"]), int(addition["raw_start"]), int(addition["raw_end"]))
            )
    return covered


def _wrap(documents: list[dict[str, object]], skipped_no_review: list[str]) -> dict[str, object]:
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "scope": "gold ground truth (harvested from review decisions + confirmed dev feedback)",
        "source": "pii_review_result + pii_feedback",
        "documents": documents,
        "skipped_without_review": sorted(skipped_no_review),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harvest gold GT from review decisions.")
    parser.add_argument("--document-data-dir", type=Path, default=Path("volumes/document-store"))
    parser.add_argument("--out", type=Path, required=True, help="Gold GT JSON output path.")
    parser.add_argument("--filenames", type=str, default=None, help="Comma-separated filter.")
    args = parser.parse_args(argv)

    filenames = [f.strip() for f in args.filenames.split(",")] if args.filenames else None
    gold = build_groundtruth(args.document_data_dir, filenames=filenames)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(gold, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    documents = gold["documents"]
    assert isinstance(documents, list)

    def _stat(key: str) -> int:
        return sum(int((d["harvest_stats"] or {}).get(key, 0)) for d in documents)  # type: ignore[index,union-attr]

    total = sum(int(d["totals"]["entity_count"]) for d in documents)  # type: ignore[index,call-overload]
    rejected, manual, feedback = _stat("rejected"), _stat("manual_confirmed"), _stat("feedback_confirmed")
    print(f"Wrote gold GT: {args.out} ({len(documents)} documents, {total} confirmed anchors)")
    print(
        f"  rejected false positives: {rejected} | manual additions: {manual} | "
        f"feedback-confirmed: {feedback}"
    )
    if rejected == 0 and manual == 0 and feedback == 0:
        print("  NOTE: no rejections, manual additions, or 'correct' feedback found — this looks "
              "like unreviewed detections, not a gold standard. Review the documents first.")
    skipped = gold["skipped_without_review"]
    assert isinstance(skipped, list)
    if skipped:
        print(f"  skipped (no review snapshot): {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
