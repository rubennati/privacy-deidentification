from __future__ import annotations

import pytest
from privacy_guard import (
    PrivacyGuardError,
    assert_report_is_safe,
    assert_text_is_safe,
    find_forbidden_keys,
    scan_for_pii_patterns,
)


def test_find_forbidden_keys_detects_blocked_field_names() -> None:
    obj = {"documents": [{"entity_type": "PERSON", "text": "Max Mustermann"}]}
    hits = find_forbidden_keys(obj)
    assert hits == ["$.documents[0].text"]


def test_find_forbidden_keys_ignores_safe_field_names() -> None:
    obj = {
        "entity_type": "PERSON",
        "count": 3,
        "text_source": "pdf_text_layer",
        "audit_result": "present",
    }
    assert find_forbidden_keys(obj) == []


def test_find_forbidden_keys_is_case_insensitive() -> None:
    assert find_forbidden_keys({"Masked_Value": "Joh***on"}) == ["$.Masked_Value"]


def test_scan_for_pii_patterns_detects_email() -> None:
    hits = scan_for_pii_patterns({"note": "contact max.mustermann@example.at for details"})
    assert any(hit.endswith(":email") for hit in hits)


def test_scan_for_pii_patterns_detects_iban() -> None:
    hits = scan_for_pii_patterns("AT611904300234573201")
    assert any(hit.endswith(":iban") for hit in hits)


def test_scan_for_pii_patterns_clean_report_has_no_hits() -> None:
    obj = {"entity_type": "EMAIL_ADDRESS", "tp": 3, "fp": 1, "fn": 2, "precision": 0.75}
    assert scan_for_pii_patterns(obj) == []


def test_assert_report_is_safe_raises_on_forbidden_key() -> None:
    with pytest.raises(PrivacyGuardError):
        assert_report_is_safe({"entities": [{"text": "leaked value"}]})


def test_assert_report_is_safe_raises_on_pii_pattern() -> None:
    with pytest.raises(PrivacyGuardError):
        assert_report_is_safe({"note": "reach me at someone@example.com"})


def test_assert_report_is_safe_passes_on_clean_report() -> None:
    clean = {
        "documents": [{"document_id": "abc123", "entity_type": "PERSON", "tp": 1, "fp": 0}],
        "global": {"precision": 0.5, "recall": 0.5},
    }
    assert_report_is_safe(clean)  # must not raise


def test_assert_text_is_safe_raises_on_pii_pattern_in_markdown() -> None:
    with pytest.raises(PrivacyGuardError):
        assert_text_is_safe("| Document | Contact |\n|---|---|\n| a.pdf | someone@example.com |")


def test_assert_text_is_safe_passes_on_clean_markdown() -> None:
    assert_text_is_safe("| Document | TP | FP |\n|---|---:|---:|\n| a.pdf | 3 | 1 |")


def test_privacy_guard_error_message_never_includes_the_matched_value() -> None:
    try:
        assert_report_is_safe({"note": "reach me at someone@example.com"})
    except PrivacyGuardError as exc:
        assert "someone@example.com" not in str(exc)
    else:
        pytest.fail("expected PrivacyGuardError")
