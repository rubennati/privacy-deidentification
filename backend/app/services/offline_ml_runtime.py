"""Pin the ML stack to local-only model/data resolution at runtime.

The api and ocr-worker run on an ``internal: true`` backend network with no egress, and all models
(OCR, the GLiNER head, and its mdeberta-v3-base backbone) are provisioned locally and mounted
read-only. This module makes the libraries actually *behave* offline so a DSGVO deployment can prove
that no request — not just no document data — leaves the machine at runtime:

- **HuggingFace / transformers** are pinned offline (``HF_HUB_OFFLINE`` / ``TRANSFORMERS_OFFLINE``).
  Compose already sets these; the ``setdefault`` here also covers tests and non-Compose runs. They
  must be set before ``transformers`` is first imported, which happens lazily on the first PII
  request — well after this module is imported at app startup.
- **tldextract** (used by Presidio's ``EmailRecognizer`` to validate email domains) is switched to
  its bundled public-suffix snapshot instead of fetching the list from the internet on first use.
  Without this it attempts an outbound request that the network isolation blocks, adding latency and
  noise on every analysis and leaving a failed-egress trace an auditor would flag.

The configuration is idempotent; :func:`configure_offline_ml_runtime` is called on import and may be
called again explicitly. It never raises — a hardening step must not block startup.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Environment flags that force HuggingFace Hub / transformers to resolve only from local files.
_HF_OFFLINE_ENV = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")


def configure_offline_ml_runtime() -> None:
    """Apply all offline pins. Safe to call more than once and never raises."""
    for name in _HF_OFFLINE_ENV:
        os.environ.setdefault(name, "1")
    _configure_tldextract_offline()


def _configure_tldextract_offline() -> None:
    """Make tldextract resolve domains only from its bundled snapshot (no runtime fetch)."""
    try:
        import tldextract
        from tldextract import suffix_list
    except ImportError:
        return
    try:
        # Belt: the module-level extractor Presidio calls via ``tldextract.extract()`` is
        # snapshot-only (``suffix_list_urls=()`` disables every remote URL).
        tldextract.TLD_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=())

        # Suspenders: force *every* extractor — whatever its configured urls, and regardless of
        # import order — to skip the remote public-suffix fetch and fall back to the packaged
        # snapshot. Reassigning ``TLD_EXTRACTOR`` alone loses a race where a default (url-bearing)
        # extractor is used at request time before the reassignment is visible. tldextract's
        # ``_get_suffix_lists`` catches ``SuffixListNotFound`` and reads the bundled
        # ``.tld_set_snapshot`` (``fallback_to_snapshot`` defaults True), so this stays offline.
        def _offline_no_remote_fetch(*_args: object, **_kwargs: object) -> str:
            raise suffix_list.SuffixListNotFound(
                "offline: remote public-suffix-list fetch is disabled"
            )

        suffix_list.find_first_response = _offline_no_remote_fetch
        logger.info("pinned tldextract to its bundled snapshot (no runtime public-suffix fetch)")
    except Exception:  # pragma: no cover - defensive; a hardening step must never break startup
        logger.warning("could not pin tldextract to offline snapshot", exc_info=True)


configure_offline_ml_runtime()
