"""Read-only capability checks for the optional OCR and PII runtimes.

These answer "is the required package/model installed" using only `importlib.util.find_spec`
(package lookup, no import/execution) and directory presence checks — never importing PaddleOCR,
spaCy, or Presidio, so calling this has no memory/CPU cost and cannot itself trigger the failures
it reports on. It exists purely to let `/api/config` tell the frontend when a station's runtime is
genuinely not installed, instead of that only being discoverable via a live request's 503.
"""

from __future__ import annotations

from importlib.util import find_spec

from app.config import Settings


def ocr_runtime_available(settings: Settings) -> bool:
    """True when PaddleOCR/PaddlePaddle are installed and the local models are provisioned.

    Mirrors the two conditions `PaddleOcrAdapter` needs before it will even attempt to build an
    engine (see ``ocr_adapters.PaddleOcrAdapter._local_model_directories``). Note: the
    ``paddlepaddle`` PyPI distribution is imported as ``paddle``, not ``paddlepaddle``.
    """
    if find_spec("paddleocr") is None or find_spec("paddle") is None:
        return False
    model_dir = settings.ocr_model_dir
    if model_dir is None:
        return False
    return (model_dir / "text_detection").is_dir() and (model_dir / "text_recognition").is_dir()


def pii_runtime_available(settings: Settings) -> bool:
    """True when Presidio, spaCy, and the configured spaCy model package are installed."""
    if find_spec("presidio_analyzer") is None or find_spec("spacy") is None:
        return False
    return find_spec(settings.pii_spacy_model) is not None
