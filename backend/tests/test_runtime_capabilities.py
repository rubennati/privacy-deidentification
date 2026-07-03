"""Tests for the read-only OCR/PII runtime capability checks."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.config import Settings
from app.services.runtime_capabilities import (
    container_memory_limit_bytes,
    ocr_memory_limit_is_low,
    ocr_runtime_available,
    pii_runtime_available,
    warn_if_ocr_memory_limit_is_low,
)


def _installed_ocr_settings(tmp_path: Path) -> Settings:
    model_dir = tmp_path / "ocr"
    (model_dir / "text_detection").mkdir(parents=True)
    (model_dir / "text_recognition").mkdir(parents=True)
    return Settings(ocr_model_dir=model_dir)


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
        _fake_find_spec({"paddleocr", "paddle"}),
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
        _fake_find_spec({"paddleocr", "paddle"}),
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
        _fake_find_spec({"paddleocr", "paddle"}),
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


def test_container_memory_limit_reads_cgroup_v2_max_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_max = tmp_path / "memory.max"
    memory_max.write_text("536870912\n")
    monkeypatch.setattr(
        "app.services.runtime_capabilities._CGROUP_V2_MEMORY_MAX_PATH", memory_max
    )

    assert container_memory_limit_bytes() == 536870912


def test_container_memory_limit_is_none_when_cgroup_v2_reports_max(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_max = tmp_path / "memory.max"
    memory_max.write_text("max\n")
    monkeypatch.setattr(
        "app.services.runtime_capabilities._CGROUP_V2_MEMORY_MAX_PATH", memory_max
    )

    assert container_memory_limit_bytes() is None


def test_container_memory_limit_falls_back_to_cgroup_v1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v1_limit = tmp_path / "memory.limit_in_bytes"
    v1_limit.write_text("2147483648\n")
    monkeypatch.setattr(
        "app.services.runtime_capabilities._CGROUP_V2_MEMORY_MAX_PATH", tmp_path / "missing"
    )
    monkeypatch.setattr(
        "app.services.runtime_capabilities._CGROUP_V1_MEMORY_LIMIT_PATH", v1_limit
    )

    assert container_memory_limit_bytes() == 2147483648


def test_container_memory_limit_is_none_when_cgroup_v1_reports_unlimited_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v1_limit = tmp_path / "memory.limit_in_bytes"
    v1_limit.write_text("9223372036854771712\n")
    monkeypatch.setattr(
        "app.services.runtime_capabilities._CGROUP_V2_MEMORY_MAX_PATH", tmp_path / "missing"
    )
    monkeypatch.setattr(
        "app.services.runtime_capabilities._CGROUP_V1_MEMORY_LIMIT_PATH", v1_limit
    )

    assert container_memory_limit_bytes() is None


def test_container_memory_limit_is_none_when_neither_cgroup_file_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.runtime_capabilities._CGROUP_V2_MEMORY_MAX_PATH", tmp_path / "missing-v2"
    )
    monkeypatch.setattr(
        "app.services.runtime_capabilities._CGROUP_V1_MEMORY_LIMIT_PATH", tmp_path / "missing-v1"
    )

    assert container_memory_limit_bytes() is None


def test_ocr_memory_limit_is_low_when_ocr_installed_under_slim_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _installed_ocr_settings(tmp_path)
    monkeypatch.setattr(
        "app.services.runtime_capabilities.find_spec", _fake_find_spec({"paddleocr", "paddle"})
    )
    monkeypatch.setattr(
        "app.services.runtime_capabilities.container_memory_limit_bytes", lambda: 512 * 1024 * 1024
    )

    assert ocr_memory_limit_is_low(settings) is True


def test_ocr_memory_limit_is_not_low_when_limit_meets_the_recommended_minimum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _installed_ocr_settings(tmp_path)
    monkeypatch.setattr(
        "app.services.runtime_capabilities.find_spec", _fake_find_spec({"paddleocr", "paddle"})
    )
    monkeypatch.setattr(
        "app.services.runtime_capabilities.container_memory_limit_bytes",
        lambda: 2 * 1024 * 1024 * 1024,
    )

    assert ocr_memory_limit_is_low(settings) is False


def test_ocr_memory_limit_is_not_low_when_limit_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable/unbounded limit must not be reported as a problem — 'unknown' stays silent
    rather than guessing, matching the same conservative default as the other capability checks."""
    settings = _installed_ocr_settings(tmp_path)
    monkeypatch.setattr(
        "app.services.runtime_capabilities.find_spec", _fake_find_spec({"paddleocr", "paddle"})
    )
    monkeypatch.setattr(
        "app.services.runtime_capabilities.container_memory_limit_bytes", lambda: None
    )

    assert ocr_memory_limit_is_low(settings) is False


def test_ocr_memory_limit_is_not_low_when_ocr_runtime_is_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(ocr_model_dir=None)
    monkeypatch.setattr("app.services.runtime_capabilities.find_spec", _fake_find_spec(set()))
    monkeypatch.setattr(
        "app.services.runtime_capabilities.container_memory_limit_bytes", lambda: 512 * 1024 * 1024
    )

    assert ocr_memory_limit_is_low(settings) is False


def test_warn_if_ocr_memory_limit_is_low_logs_a_warning_and_returns_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _installed_ocr_settings(tmp_path)
    monkeypatch.setattr(
        "app.services.runtime_capabilities.find_spec", _fake_find_spec({"paddleocr", "paddle"})
    )
    monkeypatch.setattr(
        "app.services.runtime_capabilities.container_memory_limit_bytes", lambda: 512 * 1024 * 1024
    )
    logger = logging.getLogger("app.test.runtime_capabilities")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        result = warn_if_ocr_memory_limit_is_low(settings, logger)

    assert result is True
    assert any("memory limit" in record.getMessage() for record in caplog.records)


def test_warn_if_ocr_memory_limit_is_low_stays_silent_when_not_low(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _installed_ocr_settings(tmp_path)
    monkeypatch.setattr(
        "app.services.runtime_capabilities.find_spec", _fake_find_spec({"paddleocr", "paddle"})
    )
    monkeypatch.setattr(
        "app.services.runtime_capabilities.container_memory_limit_bytes",
        lambda: 2 * 1024 * 1024 * 1024,
    )
    logger = logging.getLogger("app.test.runtime_capabilities")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        result = warn_if_ocr_memory_limit_is_low(settings, logger)

    assert result is False
    assert caplog.records == []
