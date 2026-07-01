"""Defense-in-depth guard against raw PII/text leaking into benchmark reports.

The runner is designed to never load raw text/value fields into memory in the first place
(see ``artifact_loader.py`` and ``document_matching.py``, which only ever keep counts, types,
statuses, and offsets). This module is the last-resort check, run immediately before any report
is written, so a future bug that adds a text-bearing field fails loudly instead of silently
shipping a report that contains PII.
"""

from __future__ import annotations

import re
from typing import Any

# Field names that must never appear anywhere in a report structure. Matched case-insensitively
# against dict keys at any nesting depth.
FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "value",
        "text",
        "entity_text",
        "raw_text",
        "full_text",
        "masked_value",
        "page_text",
        "ocr_text",
        "source_text",
        "snippet",
        "excerpt",
    }
)

# Obvious PII-shaped strings. This is a coarse last-resort net, not a detector: it exists to
# catch accidental leakage of a raw value, not to evaluate detection quality.
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
    "phone": re.compile(r"(?:\+|00)\d{6,15}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "ipv4": re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),
}


class PrivacyGuardError(ValueError):
    """Raised when a report structure fails a privacy guard check."""


def find_forbidden_keys(obj: Any, path: str = "$") -> list[str]:
    """Recursively find forbidden field names in a JSON-like structure.

    Returns dotted/indexed paths (e.g. ``$.documents[2].text``), never the offending value.
    """
    hits: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_path = f"{path}.{key}"
            if str(key).lower() in FORBIDDEN_KEYS:
                hits.append(key_path)
            hits.extend(find_forbidden_keys(value, key_path))
    elif isinstance(obj, (list, tuple)):
        for index, item in enumerate(obj):
            hits.extend(find_forbidden_keys(item, f"{path}[{index}]"))
    return hits


def scan_for_pii_patterns(obj: Any, path: str = "$") -> list[str]:
    """Recursively scan string leaves for obvious PII-shaped patterns.

    Returns only ``path:pattern_name`` markers, never the matched substring, so the violation
    report itself cannot re-leak the value it is warning about.
    """
    hits: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            hits.extend(scan_for_pii_patterns(value, f"{path}.{key}"))
    elif isinstance(obj, (list, tuple)):
        for index, item in enumerate(obj):
            hits.extend(scan_for_pii_patterns(item, f"{path}[{index}]"))
    elif isinstance(obj, str):
        for name, pattern in _PII_PATTERNS.items():
            if pattern.search(obj):
                hits.append(f"{path}:{name}")
    return hits


def assert_text_is_safe(text: str) -> None:
    """Raise ``PrivacyGuardError`` if a rendered text (e.g. the markdown report) contains a
    PII-shaped string. Forbidden-key checks do not apply to free text, only the pattern scan."""
    hits = scan_for_pii_patterns(text)
    if hits:
        raise PrivacyGuardError(
            "Privacy guard blocked report generation — PII-shaped strings at: "
            + ", ".join(hits[:20])
        )


def assert_report_is_safe(report: Any) -> None:
    """Raise ``PrivacyGuardError`` if the report contains forbidden fields or PII-shaped strings."""
    forbidden = find_forbidden_keys(report)
    pattern_hits = scan_for_pii_patterns(report)
    if not forbidden and not pattern_hits:
        return
    parts = []
    if forbidden:
        parts.append(f"forbidden fields at: {', '.join(forbidden[:20])}")
    if pattern_hits:
        parts.append(f"PII-shaped strings at: {', '.join(pattern_hits[:20])}")
    raise PrivacyGuardError("Privacy guard blocked report generation — " + "; ".join(parts))
