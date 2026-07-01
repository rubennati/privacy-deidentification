from __future__ import annotations

from document_matching import (
    LocalDocRef,
    is_unsupported_file_type,
    match_documents,
    normalize_whitespace,
    strip_copy_suffix,
)


def test_strip_copy_suffix_removes_trailing_number_in_parens() -> None:
    assert strip_copy_suffix("Angebot_AN2607003(1).pdf") == "Angebot_AN2607003.pdf"
    assert strip_copy_suffix("Angebot-AN2605008_Szihn-GmbH(2).pdf") == "Angebot-AN2605008_Szihn-GmbH.pdf"


def test_strip_copy_suffix_is_a_no_op_without_a_suffix() -> None:
    assert strip_copy_suffix("Angebot_AN2607003.pdf") == "Angebot_AN2607003.pdf"


def test_normalize_whitespace_trims_but_does_not_strip_suffix() -> None:
    assert normalize_whitespace("  Report.pdf ") == "Report.pdf"
    assert normalize_whitespace("Report(1).pdf") == "Report(1).pdf"


def test_is_unsupported_file_type_flags_txt() -> None:
    assert is_unsupported_file_type("insurance-letter.txt") is True
    assert is_unsupported_file_type("insurance-letter.pdf") is False


def test_exact_filename_match() -> None:
    local = [LocalDocRef(document_id="doc-1", filename="Report.pdf", size_bytes=100)]
    result = match_documents(local, [("Report.pdf", 100)])
    assert len(result.matched) == 1
    assert result.matched[0].match_basis == "exact_filename"
    assert result.matched[0].size_matches is True
    assert result.unmatched_local_documents == ()
    assert result.unmatched_benchmark_entries == ()


def test_suffix_stripped_match_for_copy_suffix_filenames() -> None:
    local = [LocalDocRef(document_id="doc-1", filename="Angebot_AN2607003.pdf", size_bytes=100)]
    result = match_documents(local, [("Angebot_AN2607003(1).pdf", 100)])
    assert len(result.matched) == 1
    assert result.matched[0].match_basis == "suffix_stripped"
    assert result.matched[0].benchmark_filename == "Angebot_AN2607003(1).pdf"


def test_unmatched_local_document_reported_when_no_candidate() -> None:
    local = [LocalDocRef(document_id="doc-1", filename="Unrelated.pdf", size_bytes=100)]
    result = match_documents(local, [("Other.pdf", 100)])
    assert result.unmatched_local_documents == ("doc-1",)
    assert result.unmatched_benchmark_entries == ("Other.pdf",)
    assert result.matched == ()


def test_unsupported_file_type_entry_is_not_reported_as_generic_unmatched() -> None:
    local: list[LocalDocRef] = []
    result = match_documents(local, [("insurance-letter.txt", 400)])
    assert result.unmatched_benchmark_entries == ()
    assert result.unsupported_file_type_entries == ("insurance-letter.txt",)


def test_ambiguous_match_reported_when_size_cannot_disambiguate() -> None:
    local = [LocalDocRef(document_id="doc-1", filename="Report.pdf", size_bytes=None)]
    # Two benchmark entries share the same normalized/suffix-stripped name.
    result = match_documents(local, [("Report(1).pdf", 100), ("Report(2).pdf", 200)])
    assert result.matched == ()
    assert len(result.ambiguous_matches) == 1
    ambiguous = result.ambiguous_matches[0]
    assert ambiguous.local_document_id == "doc-1"
    assert set(ambiguous.candidate_benchmark_filenames) == {"Report(1).pdf", "Report(2).pdf"}


def test_size_plausibility_disambiguates_between_candidates() -> None:
    local = [LocalDocRef(document_id="doc-1", filename="Report.pdf", size_bytes=200)]
    result = match_documents(local, [("Report(1).pdf", 100), ("Report(2).pdf", 200)])
    assert len(result.matched) == 1
    assert result.matched[0].benchmark_filename == "Report(2).pdf"
    assert result.matched[0].match_basis == "suffix_stripped+size_plausibility"
    assert result.ambiguous_matches == ()


def test_local_document_without_filename_is_unmatched() -> None:
    local = [LocalDocRef(document_id="doc-1", filename=None, size_bytes=None)]
    result = match_documents(local, [("Report.pdf", 100)])
    assert result.unmatched_local_documents == ("doc-1",)
