"""Read-only capability checks for the optional OCR and PII runtimes.

These answer "is the required package/model installed" using only `importlib.util.find_spec`
(package lookup, no import/execution) and directory presence checks — never importing PaddleOCR,
spaCy, or Presidio, so calling this has no memory/CPU cost and cannot itself trigger the failures
it reports on. It exists purely to let `/api/config` tell the frontend when a station's runtime is
genuinely not installed, instead of that only being discoverable via a live request's 503.
"""

from __future__ import annotations

import logging
from importlib.util import find_spec
from pathlib import Path

from app.config import Settings

# cgroup v1 reports an implementation-defined huge sentinel (commonly (1 << 64) - 1 rounded down
# to a page boundary) rather than a literal "unlimited" marker; anything at this scale is treated
# as "no real limit" rather than a number to compare against.
_CGROUP_V1_UNLIMITED_THRESHOLD = 1 << 62
_CGROUP_V2_MEMORY_MAX_PATH = Path("/sys/fs/cgroup/memory.max")
_CGROUP_V1_MEMORY_LIMIT_PATH = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
# Sync OCR fallback needs real headroom for PaddlePaddle. The default stack runs OCR in the
# ocr-worker with its own memory ceiling, but an explicitly synchronous API should still warn when
# it is too small to survive OCR in-process.
_OCR_RECOMMENDED_MINIMUM_MEMORY_BYTES = 1024 * 1024 * 1024


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


def container_memory_limit_bytes() -> int | None:
    """Best-effort read of this process's cgroup memory limit, in bytes.

    Returns ``None`` when the limit is unavailable (not running under a memory-limited cgroup,
    e.g. local dev outside a container) or unbounded, so callers treat "unknown" the same as "no
    evidence of a problem" rather than guessing. Tries cgroup v2 first, then v1.
    """
    try:
        raw = _CGROUP_V2_MEMORY_MAX_PATH.read_text().strip()
    except OSError:
        raw = None
    if raw is not None:
        if raw == "max":
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    try:
        raw = _CGROUP_V1_MEMORY_LIMIT_PATH.read_text().strip()
    except OSError:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return None if value >= _CGROUP_V1_UNLIMITED_THRESHOLD else value


def ocr_memory_limit_is_low(settings: Settings) -> bool:
    """True when the OCR runtime is installed but the container memory limit looks too low.

    This never runs OCR itself — it only compares the already-installed check against the cgroup
    limit already visible to the process, so it carries the same zero-cost, safe-to-call-anytime
    guarantee as ``ocr_runtime_available``.
    """
    if not ocr_runtime_available(settings):
        return False
    limit = container_memory_limit_bytes()
    if limit is None:
        return False
    return limit < _OCR_RECOMMENDED_MINIMUM_MEMORY_BYTES


def warn_if_ocr_memory_limit_is_low(settings: Settings, log: logging.Logger) -> bool:
    """Log once (e.g. at app startup) when OCR is installed but memory looks too low to run it.

    Returns the same boolean as ``ocr_memory_limit_is_low`` so a caller that already needs the
    value (like the startup hook) doesn't have to decide separately whether to log.
    """
    is_low = ocr_memory_limit_is_low(settings)
    if is_low:
        log.warning(
            "OCR runtime is installed but the container memory limit looks too low for "
            "PaddleOCR to run without being OOM-killed mid-request. Restart with "
            "API_MEMORY_LIMIT=2g when using OCR_EXECUTION_MODE=sync, or use the default "
            "worker mode."
        )
    return is_low
