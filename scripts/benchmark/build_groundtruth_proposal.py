"""Export a ground-truth PROPOSAL from the current PII detections (Weg B, gold-GT authoring).

The thin real corpus has no offset-exact, complete ground truth, so the structural-context A/B
(ADR-0043) cannot show a precision/boundary gain. Building that gold GT by hand is the blocker;
this script gives the annotator a starting point: it emits the current detections as a *proposal*
in the exact benchmark GT schema (``load_groundtruth`` reads it directly), with each entity flagged
``review_status: "proposed"``. The human then confirms / rejects / corrects offsets / adds missed
entities and freezes the result as the gold GT.

Privacy: this script is **offset-only and never reads or writes document text**. It reuses the
deliberately text-free benchmark loader (``DetectedEntity`` carries type/page/offsets/score, never a
value), so the proposal — like the GT it seeds — is anchors only. A reviewer judges each anchor in
the Review UI, which renders the document. (A private, opt-in text-context companion for CLI-only
annotation is a deliberate follow-up, not part of this offset-only cut.)
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from artifact_loader import DetectedEntity, DocumentArtifacts, PiiSummary, load_local_corpus

_INSTRUCTIONS = (
    "REVIEW REQUIRED — this is a proposal from detections, not a gold standard.",
    "For each entity set review_status to confirmed | rejected | corrected.",
    "Fix start/end (page-local offsets) and entity_type where the detection is off.",
    "Add entities the detector missed (review_status: added); remove nothing — reject instead.",
    "Types outside the run's configured_entity_types cannot appear here; add them by hand.",
    "Once confirmed, drop the review_* fields or point the benchmark at this file as-is.",
)


def _entity_anchor(entity: DetectedEntity) -> dict[str, object] | None:
    """One proposed anchor in the GT schema (+ review metadata). None if it has no usable offsets."""
    if entity.page_number is not None:
        if entity.page_start_offset is None or entity.page_end_offset is None:
            return None
        page, start, end = entity.page_number, entity.page_start_offset, entity.page_end_offset
    else:
        # Non-paged document (e.g. DOCX): GT matches by type counts, offsets are not compared.
        page, start, end = None, entity.start_offset, entity.end_offset
    return {
        "entity_type": entity.entity_type,
        "page": page,
        "start": start,
        "end": end,
        # Review metadata — ignored by load_groundtruth, present for the annotator only.
        "review_status": "proposed",
        "detection_source": entity.recognizer,
        "score": entity.score,
    }


def _document_proposal(doc: DocumentArtifacts, pii: PiiSummary, min_score: float) -> dict[str, object]:
    anchors: list[dict[str, object]] = []
    for entity in pii.entities:
        if entity.score is not None and entity.score < min_score:
            continue
        anchor = _entity_anchor(entity)
        if anchor is not None:
            anchors.append(anchor)
    by_type: dict[str, int] = {}
    for anchor in anchors:
        entity_type = str(anchor["entity_type"])
        by_type[entity_type] = by_type.get(entity_type, 0) + 1
    return {
        "filename": doc.document.display_filename,
        "document_id": doc.document.document_id,
        "pages_count": len(doc.text.pages) if doc.text is not None else None,
        "profile": pii.profile,
        "configured_entity_types": list(pii.configured_entity_types),
        "needs_review": True,
        "entities": anchors,
        "totals": {"entity_count": len(anchors), "by_type": dict(sorted(by_type.items()))},
    }


def _select_pii(doc: DocumentArtifacts, profile: str | None) -> PiiSummary | None:
    if profile is None:
        return doc.pii
    return doc.pii_by_profile.get(profile)


def build_proposal(
    corpus: Sequence[DocumentArtifacts],
    *,
    filenames: Sequence[str] | None = None,
    min_score: float = 0.0,
    profile: str | None = None,
) -> dict[str, object]:
    """Build an offset-only GT proposal from loaded artifacts. Deterministic and text-free."""
    wanted = set(filenames) if filenames else None
    documents: list[dict[str, object]] = []
    for doc in sorted(corpus, key=lambda d: d.document.display_filename or d.document.document_id):
        name = doc.document.display_filename
        if wanted is not None and name not in wanted:
            continue
        pii = _select_pii(doc, profile)
        if name is None or pii is None:
            continue
        documents.append(_document_proposal(doc, pii, min_score))
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "scope": "ground-truth proposal (from PII detections) — REVIEW REQUIRED",
        "source": "pii_detection",
        "instructions": list(_INSTRUCTIONS),
        "documents": documents,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a GT proposal from current PII detections.")
    parser.add_argument("--uploads-dir", type=Path, default=Path("volumes/uploads"))
    parser.add_argument("--document-data-dir", type=Path, default=Path("volumes/document-store"))
    parser.add_argument("--out", type=Path, required=True, help="Proposal JSON output path.")
    parser.add_argument("--filenames", type=str, default=None, help="Comma-separated filter.")
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--profile", type=str, default=None, help="Use this profile's PII artifact.")
    args = parser.parse_args(argv)

    corpus = load_local_corpus(args.uploads_dir, args.document_data_dir)
    filenames = [f.strip() for f in args.filenames.split(",")] if args.filenames else None
    proposal = build_proposal(
        corpus, filenames=filenames, min_score=args.min_score, profile=args.profile
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(proposal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    docs = proposal["documents"]
    assert isinstance(docs, list)
    total = sum(int(d["totals"]["entity_count"]) for d in docs)  # type: ignore[index,call-overload]
    print(f"Wrote GT proposal: {args.out} ({len(docs)} documents, {total} proposed anchors)")
    print("REVIEW REQUIRED before use as gold ground truth — see the file's instructions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
