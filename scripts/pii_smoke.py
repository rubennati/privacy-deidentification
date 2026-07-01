"""Smoke-test the real Presidio/spaCy PII runtime.

Deliberately not part of ``make test``: it needs the PII image extra and the spaCy model. Run
via ``make pii-smoke``. Uses a synthetic e-mail address only — no real or sample data.
"""

from __future__ import annotations

from app.config import get_settings
from app.services.pii_adapters import PiiUnavailableError, PresidioAnalyzerAdapter

_SAMPLE = "Kontakt: max@example.at"


def main() -> int:
    settings = get_settings()
    adapter = PresidioAnalyzerAdapter(settings.pii_language, settings.pii_spacy_model)
    try:
        results = adapter.analyze(_SAMPLE, settings.pii_language, ("EMAIL_ADDRESS",), 0.5)
    except PiiUnavailableError:
        print(
            "FAIL: PII runtime unavailable — Presidio/spaCy or the model is missing. "
            "Build with INSTALL_PII=true."
        )
        return 1

    print(f"detected: {[(r.entity_type, round(r.score, 2)) for r in results]}")
    if not any(r.entity_type == "EMAIL_ADDRESS" for r in results):
        print("FAIL: expected EMAIL_ADDRESS was not detected.")
        return 1
    print("OK: PII runtime detected EMAIL_ADDRESS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
