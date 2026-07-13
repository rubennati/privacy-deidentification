"""Availability + failure-surfacing contract for the local GLiNER detector (model-free)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.services.pii_ner_gliner import GlinerNerDetector, GlinerUnavailableError


def test_handled_types_are_person_and_organization() -> None:
    detector = GlinerNerDetector(Path("/nonexistent"), "model")
    assert detector.handled_types() == frozenset({"PERSON", "ORGANIZATION"})


def test_detect_short_circuits_without_touching_the_model(tmp_path: Path) -> None:
    # A missing model dir would raise if reached; these inputs must never reach the model.
    detector = GlinerNerDetector(tmp_path, "does-not-exist")
    assert detector.detect("Max Mustermann", ("EMAIL_ADDRESS",), 0.5) == []
    assert detector.detect("   ", ("PERSON",), 0.5) == []


def test_missing_model_dir_raises_unavailable_and_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    detector = GlinerNerDetector(tmp_path, "does-not-exist")
    with caplog.at_level(logging.ERROR), pytest.raises(GlinerUnavailableError):
        detector.detect("Max Mustermann", ("PERSON",), 0.5)
    assert any("not found" in record.getMessage() for record in caplog.records)


def test_load_failure_surfaces_real_cause_and_raises_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "gliner_multi-v2.1").mkdir()

    def _boom(name: str) -> object:
        raise OSError("Can't load the configuration of 'microsoft/mdeberta-v3-base'")

    monkeypatch.setattr("app.services.pii_ner_gliner.import_module", _boom)

    detector = GlinerNerDetector(tmp_path, "gliner_multi-v2.1")
    with caplog.at_level(logging.ERROR), pytest.raises(GlinerUnavailableError) as excinfo:
        detector.detect("Max Mustermann", ("PERSON",), 0.5)

    # The generic 503 is raised, but chained to — and logging — the real cause, not swallowing it.
    assert isinstance(excinfo.value.__cause__, OSError)
    messages = [record.getMessage() for record in caplog.records]
    assert any("failed to load" in message for message in messages)
    assert any("mdeberta-v3-base" in message for message in messages)
