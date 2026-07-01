"""Model-free contract tests for the production PaddleOCR adapter boundary."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.ocr_adapters import OcrUnavailableError, PaddleOcrAdapter


def test_unconfigured_models_fail_before_paddle_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_import(name: str) -> object:
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("app.services.ocr_adapters.import_module", fail_import)

    with pytest.raises(OcrUnavailableError):
        PaddleOcrAdapter(None).extract_text(tmp_path / "image.png")


def test_incomplete_model_directory_fails_before_paddle_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "text_detection").mkdir()

    def fail_import(name: str) -> object:
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("app.services.ocr_adapters.import_module", fail_import)

    with pytest.raises(OcrUnavailableError):
        PaddleOcrAdapter(tmp_path).extract_text(tmp_path / "image.png")


def test_local_models_are_loaded_lazily_and_results_are_parsed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    detection_dir = tmp_path / "text_detection"
    recognition_dir = tmp_path / "text_recognition"
    detection_dir.mkdir()
    recognition_dir.mkdir()
    initialization_arguments: list[dict[str, object]] = []

    class FakeEngine:
        def predict(self, input: str) -> object:
            assert input.endswith("image.png")
            return [SimpleNamespace(json={"res": {"rec_texts": ["First", "Second"]}})]

    def paddle_ocr(**kwargs: object) -> FakeEngine:
        initialization_arguments.append(kwargs)
        return FakeEngine()

    monkeypatch.setattr(
        "app.services.ocr_adapters.import_module",
        lambda name: SimpleNamespace(PaddleOCR=paddle_ocr),
    )
    adapter = PaddleOcrAdapter(tmp_path)
    assert initialization_arguments == []

    text = adapter.extract_text(tmp_path / "image.png")

    assert text == "First\nSecond"
    assert initialization_arguments == [
        {
            "device": "cpu",
            "enable_mkldnn": False,
            "text_detection_model_dir": str(detection_dir),
            "text_recognition_model_dir": str(recognition_dir),
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
    ]


def test_configured_model_names_are_passed_to_paddle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "text_detection").mkdir()
    (tmp_path / "text_recognition").mkdir()
    initialization_arguments: list[dict[str, object]] = []

    class FakeEngine:
        def predict(self, input: str) -> object:
            return [SimpleNamespace(json={"res": {"rec_texts": ["ok"]}})]

    def paddle_ocr(**kwargs: object) -> FakeEngine:
        initialization_arguments.append(kwargs)
        return FakeEngine()

    monkeypatch.setattr(
        "app.services.ocr_adapters.import_module",
        lambda name: SimpleNamespace(PaddleOCR=paddle_ocr),
    )

    PaddleOcrAdapter(
        tmp_path, "PP-OCRv5_mobile_det", "latin_PP-OCRv5_mobile_rec"
    ).extract_text(tmp_path / "image.png")

    (kwargs,) = initialization_arguments
    assert kwargs["text_detection_model_name"] == "PP-OCRv5_mobile_det"
    assert kwargs["text_recognition_model_name"] == "latin_PP-OCRv5_mobile_rec"


def test_paddle_initialization_failure_returns_503(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "text_detection").mkdir()
    (tmp_path / "text_recognition").mkdir()

    def fail_initialization(**kwargs: object) -> object:
        raise RuntimeError("simulated model initialization failure")

    monkeypatch.setattr(
        "app.services.ocr_adapters.import_module",
        lambda name: SimpleNamespace(PaddleOCR=fail_initialization),
    )

    with pytest.raises(OcrUnavailableError) as exc_info:
        PaddleOcrAdapter(tmp_path).extract_text(tmp_path / "image.png")

    assert exc_info.value.status_code == 503
