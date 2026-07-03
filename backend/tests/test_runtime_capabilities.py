"""Tests for the read-only OCR/PII runtime capability checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.services.runtime_capabilities import ocr_runtime_available, pii_runtime_available


def _fake_find_spec(available: set[str]):
    def find_spec(name: str) -> object | None:
        return object() if name in available else None

    return find_spec


def test_ocr_runtime_available_when_packages_installed_and_models_provisioned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_dir = tmp_path / "ocr"
    (model_dir / "text_detection").mkdir(parents=True)
    (model_dir / "text_recognition").mkdir(parents=True)
    settings = Settings(ocr_model_dir=model_dir)
    monkeypatch.setattr(
        "app.services.runtime_capabilities.find_spec",
        _fake_find_spec({"paddleocr", "paddlepaddle"}),
    )

    assert ocr_runtime_available(settings) is True


def test_ocr_runtime_unavailable_when_packages_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_dir = tmp_path / "ocr"
    (model_dir / "text_detection").mkdir(parents=True)
    (model_dir / "text_recognition").mkdir(parents=True)
    settings = Settings(ocr_model_dir=model_dir)
    monkeypatch.setattr("app.services.runtime_capabilities.find_spec", _fake_find_spec(set()))

    assert ocr_runtime_available(settings) is False


def test_ocr_runtime_unavailable_when_models_not_provisioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(ocr_model_dir=None)
    monkeypatch.setattr(
        "app.services.runtime_capabilities.find_spec",
        _fake_find_spec({"paddleocr", "paddlepaddle"}),
    )

    assert ocr_runtime_available(settings) is False


def test_ocr_runtime_unavailable_when_model_subdirectories_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_dir = tmp_path / "ocr"
    model_dir.mkdir()
    settings = Settings(ocr_model_dir=model_dir)
    monkeypatch.setattr(
        "app.services.runtime_capabilities.find_spec",
        _fake_find_spec({"paddleocr", "paddlepaddle"}),
    )

    assert ocr_runtime_available(settings) is False


def test_pii_runtime_available_when_packages_and_model_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(pii_spacy_model="de_core_news_sm")
    monkeypatch.setattr(
        "app.services.runtime_capabilities.find_spec",
        _fake_find_spec({"presidio_analyzer", "spacy", "de_core_news_sm"}),
    )

    assert pii_runtime_available(settings) is True


def test_pii_runtime_unavailable_when_model_package_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(pii_spacy_model="de_core_news_sm")
    monkeypatch.setattr(
        "app.services.runtime_capabilities.find_spec",
        _fake_find_spec({"presidio_analyzer", "spacy"}),
    )

    assert pii_runtime_available(settings) is False


def test_pii_runtime_unavailable_when_packages_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(pii_spacy_model="de_core_news_sm")
    monkeypatch.setattr("app.services.runtime_capabilities.find_spec", _fake_find_spec(set()))

    assert pii_runtime_available(settings) is False
