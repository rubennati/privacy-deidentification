"""Smoke-test the real Presidio/spaCy PII runtime.

Deliberately not part of ``make test``: it needs the PII image extra and the spaCy model. Run
via ``make pii-smoke``. Uses synthetic values only — no real or private sample data.
"""

from __future__ import annotations

from app.config import get_settings
from app.services.pii_adapters import PiiUnavailableError, PresidioAnalyzerAdapter

_SAMPLE = (
    "Kontakt: max@example.at; UID: ATU12345678; "
    "SV-Nummer: 1234 120478; Polizzennummer: POL-TEST-2026-0042"
)
_ENTITY_TYPES = ("EMAIL_ADDRESS", "UID_AT", "SVNR_AT", "POLICY_NUMBER")


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
    print(f"detected types: {sorted(detected_types)}")
    missing = set(_ENTITY_TYPES).difference(detected_types)
    if missing:
        print(f"FAIL: expected entity types were not detected: {sorted(missing)}")
        return 1
    print("OK: PII runtime detected the structured and insurance-at-de smoke types.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
