"""Load private benchmark inputs and match them to local documents.

Matching strategy (in order, per the PR spec — never guess on ambiguity):

1. exact display filename
2. normalized display filename (unicode NFC + whitespace trim only)
3. filename with a trailing ``(1)``/``(2)`` copy-suffix stripped
4. size plausibility as a disambiguator when step 2/3 still yields multiple candidates
5. otherwise reported as ``ambiguous`` — the runner never guesses

Ground-truth entity anchors are loaded here too, but stripped down to
``(entity_type, page, start, end)`` — ``masked_value``, ``source``, ``value_length``, and
``value_sha256_12`` are intentionally dropped at load time so they can never reach a report.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_COPY_SUFFIX_RE = re.compile(r"^(?P<stem>.*?)(?:\s*\(\d+\))?(?P<ext>\.[A-Za-z0-9]+)$")


def normalize_whitespace(filename: str) -> str:
    """Unicode-normalize and trim whitespace only (no suffix stripping)."""
    return unicodedata.normalize("NFC", filename).strip()


def strip_copy_suffix(filename: str) -> str:
    """Strip a trailing ``(1)``/``(2)``-style copy suffix before the extension."""
    normalized = normalize_whitespace(filename)
    match = _COPY_SUFFIX_RE.match(normalized)
    if not match:
        return normalized
    return f"{match.group('stem').strip()}{match.group('ext')}"


def is_unsupported_file_type(filename: str) -> bool:
    """``.txt`` is a known, deliberate non-match (TXT is not a supported upload type yet)."""
    return filename.lower().endswith(".txt")


@dataclass(frozen=True)
class BenchmarkMetadataEntry:
    filename: str
    file_type: str | None
    size_bytes: int | None
    pages: int | None
    text_quality_bucket: str | None
    recommended_pipeline: str | None
    benchmark_role: str | None
    page_quality: tuple[str, ...]


@dataclass(frozen=True)
class GroundTruthEntityAnchor:
    """A candidate ground-truth entity, stripped of any raw/masked value content."""

    entity_type: str
    page: int | None
    start: int
    end: int


@dataclass(frozen=True)
class GroundTruthDocument:
    filename: str
    pages_count: int | None
    file_size: int | None
    entities: tuple[GroundTruthEntityAnchor, ...]
    total_entity_count: int
    entity_counts_by_type: dict[str, int]


@dataclass(frozen=True)
class LocalDocRef:
    document_id: str
    filename: str | None
    size_bytes: int | None


@dataclass(frozen=True)
class MatchedDocument:
    document_id: str
    local_filename: str
    benchmark_filename: str
    match_basis: str
    size_matches: bool | None


@dataclass(frozen=True)
class AmbiguousMatch:
    local_document_id: str
    local_filename: str
    candidate_benchmark_filenames: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class MatchResult:
    matched: tuple[MatchedDocument, ...]
    unmatched_local_documents: tuple[str, ...]
    unmatched_benchmark_entries: tuple[str, ...]
    unsupported_file_type_entries: tuple[str, ...]
    ambiguous_matches: tuple[AmbiguousMatch, ...]


def load_benchmark_metadata(path: Path) -> list[BenchmarkMetadataEntry]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = []
    for doc in raw.get("documents", []):
        entries.append(
            BenchmarkMetadataEntry(
                filename=str(doc["filename"]),
                file_type=doc.get("file_type"),
                size_bytes=doc.get("size_bytes"),
                pages=doc.get("pages"),
                text_quality_bucket=doc.get("text_quality_bucket"),
                recommended_pipeline=doc.get("recommended_pipeline"),
                benchmark_role=doc.get("benchmark_role"),
                page_quality=tuple(doc.get("page_quality") or ()),
            )
        )
    return entries


def load_groundtruth(path: Path) -> list[GroundTruthDocument]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    documents = []
    for doc in raw.get("documents", []):
        entities = tuple(
            GroundTruthEntityAnchor(
                entity_type=str(entity["entity_type"]),
                page=entity.get("page"),
                start=int(entity["start"]),
                end=int(entity["end"]),
            )
            for entity in doc.get("entities", [])
        )
        totals = doc.get("totals") or {}
        documents.append(
            GroundTruthDocument(
                filename=str(doc["filename"]),
                pages_count=doc.get("pages_count"),
                file_size=doc.get("file_size"),
                entities=entities,
                total_entity_count=int(totals.get("entity_count", len(entities))),
                entity_counts_by_type=dict(totals.get("by_type") or {}),
            )
        )
    return documents


def match_documents(
    local_documents: list[LocalDocRef],
    benchmark_filenames: list[tuple[str, int | None]],
) -> MatchResult:
    """Match local documents against a set of ``(filename, size_bytes)`` benchmark entries."""
    remaining: dict[str, int | None] = dict(benchmark_filenames)
    matched: list[MatchedDocument] = []
    ambiguous: list[AmbiguousMatch] = []
    unmatched_local: list[str] = []

    for local in local_documents:
        if not local.filename:
            unmatched_local.append(local.document_id)
            continue

        candidates, basis = _find_candidates(local.filename, remaining)
        if not candidates:
            unmatched_local.append(local.document_id)
            continue

        if len(candidates) > 1 and local.size_bytes is not None:
            size_matches = [name for name in candidates if remaining[name] == local.size_bytes]
            if len(size_matches) == 1:
                candidates = size_matches
                basis = f"{basis}+size_plausibility"

        if len(candidates) > 1:
            ambiguous.append(
                AmbiguousMatch(
                    local_document_id=local.document_id,
                    local_filename=local.filename,
                    candidate_benchmark_filenames=tuple(sorted(candidates)),
                    reason="multiple_benchmark_entries_match_local_document",
                )
            )
            continue

        chosen = candidates[0]
        chosen_size = remaining[chosen]
        size_matches_flag = (
            local.size_bytes == chosen_size
            if local.size_bytes is not None and chosen_size is not None
            else None
        )
        matched.append(
            MatchedDocument(
                document_id=local.document_id,
                local_filename=local.filename,
                benchmark_filename=chosen,
                match_basis=basis,
                size_matches=size_matches_flag,
            )
        )
        del remaining[chosen]

    unsupported = tuple(sorted(name for name in remaining if is_unsupported_file_type(name)))
    unmatched_benchmark = tuple(
        sorted(name for name in remaining if not is_unsupported_file_type(name))
    )
    return MatchResult(
        matched=tuple(matched),
        unmatched_local_documents=tuple(unmatched_local),
        unmatched_benchmark_entries=unmatched_benchmark,
        unsupported_file_type_entries=unsupported,
        ambiguous_matches=tuple(ambiguous),
    )


def _find_candidates(
    local_filename: str, remaining: dict[str, int | None]
) -> tuple[list[str], str]:
    # 1. exact
    exact = [name for name in remaining if name == local_filename]
    if exact:
        return exact, "exact_filename"

    # 2. normalized (unicode/whitespace only)
    local_norm = normalize_whitespace(local_filename)
    normalized = [name for name in remaining if normalize_whitespace(name) == local_norm]
    if normalized:
        return normalized, "normalized_filename"

    # 3. copy-suffix stripped
    local_stripped = strip_copy_suffix(local_filename)
    stripped = [name for name in remaining if strip_copy_suffix(name) == local_stripped]
    return stripped, "suffix_stripped"
