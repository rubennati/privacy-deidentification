"""Tests for logging configuration hardening."""

from __future__ import annotations

import logging

from app.logging import configure_logging


def test_presidio_analyzer_logger_is_capped_at_warning() -> None:
    configure_logging("INFO")

    presidio_logger = logging.getLogger("presidio-analyzer")
    # The INFO "recognizer loaded" burst is silenced ...
    assert not presidio_logger.isEnabledFor(logging.INFO)
    # ... but genuine problems still surface, so diagnosis is not lost.
    assert presidio_logger.isEnabledFor(logging.WARNING)
