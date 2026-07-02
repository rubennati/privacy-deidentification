"""Smoke-test the real Presidio/spaCy PII runtime end to end.

Deliberately not part of ``make test``: it needs the PII image extra and the spaCy model. Run
via ``make pii-smoke``. Uses synthetic values only — no real or private sample data.

The smoke exercises the *full* detection path used by the PII workstation: raw Presidio/spaCy
detection **and** the Engine-5 candidate-validation post-processing that runs after it. Asserting
only on raw detection (as an earlier version did) would stay green even if candidate validation
dropped or scored down every candidate, hiding exactly the kind of regression that empties the
final result. So this test also asserts that the structured/insurance types survive validation.
"""

from __future__ import annotations

from app.config import get_settings
from app.services.pii_adapters import PiiUnavailableError, PresidioAnalyzerAdapter
from app.services.pii_candidate_validation import validate_candidates

_SAMPLE = (
    "Kontakt: max@example.at; UID: ATU12345678; "
    "SV-Nummer: 1234 120478; Polizzennummer: POL-TEST-2026-0042\n"
    "Ansprechpartner: Frau Dr. Eva Muster, +43 664 1234567\n"
    "Adresse: Beispielgasse 12, 1010 Wien\n"
    "Kunde: Muster Holding GmbH"
)
_ENTITY_TYPES = (
    "EMAIL_ADDRESS",
    "UID_AT",
    "SVNR_AT",
    "POLICY_NUMBER",
    "ADDRESS",
    "CONTACT_LINE",
    "CUSTOMER_LINE",
)


def main() -> int:
    settings = get_settings()
    adapter = PresidioAnalyzerAdapter(settings.pii_language, settings.pii_spacy_model)
    try:
        results = adapter.analyze(
            _SAMPLE,
            settings.pii_language,
            _ENTITY_TYPES,
            settings.pii_score_threshold,
        )
    except PiiUnavailableError:
        print(
            "FAIL: PII runtime unavailable — Presidio/spaCy or the model is missing. "
            "Build with INSTALL_PII=true."
        )
        return 1

    detected_types = {result.entity_type for result in results}
    print(f"detected types (raw): {sorted(detected_types)}")
    missing = set(_ENTITY_TYPES).difference(detected_types)
    if missing:
        print(f"FAIL: expected entity types were not detected: {sorted(missing)}")
        return 1

    # Run the same candidate-validation pass the workstation applies before persisting the
    # result, then assert the final (post-validation) layer is non-empty and still carries the
    # expected structured/insurance types. This guards against a validation change that empties
    # the final result even though raw detection still works.
    candidates = [(result, 0, None) for result in results]
    validated, summary = validate_candidates(
        candidates, {None: _SAMPLE}, settings.pii_score_threshold, enabled=True
    )
    final_types = {item.entity.entity_type for item, _, _ in validated}
    print(f"final types (post-validation): {sorted(final_types)}")
    print(
        f"validation summary: kept={summary.kept} dropped={summary.dropped} "
        f"score_down={summary.score_down}"
    )
    if not validated:
        print("FAIL: candidate validation emptied the final result (0 surviving entities).")
        return 1
    dropped_expected = set(_ENTITY_TYPES).difference(final_types)
    if dropped_expected:
        print(
            "FAIL: candidate validation removed expected structured/insurance types: "
            f"{sorted(dropped_expected)}"
        )
        return 1
    print("OK: PII runtime detected and validation kept the structured and insurance-at-de types.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
