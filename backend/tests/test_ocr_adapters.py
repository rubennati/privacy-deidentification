"""Model-free contract tests for the production PaddleOCR adapter boundary."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services.ocr_adapters import OcrUnavailableError, PaddleOcrAdapter, extract_ocr_result


def test_legacy_text_only_adapter_remains_compatible(tmp_path: Path) -> None:
    class LegacyAdapter:
        def extract_text(self, image_path: Path) -> str:
            return "Legacy text"

        def tool_versions(self) -> dict[str, str]:
            return {"legacy": "test"}

    result = extract_ocr_result(LegacyAdapter(), tmp_path / "image.png")

    assert result.text == "Legacy text"
    assert result.confidence is None
    assert result.line_confidences == ()


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
            return [
                SimpleNamespace(
                    json={
                        "res": {
                            "rec_texts": ["First", "Second"],
                            "rec_scores": [0.8, 0.6],
                            "rec_polys": [
                                [[10, 20], [90, 20], [90, 40], [10, 40]],
                                [[10, 50], [110, 50], [110, 70], [10, 70]],
                            ],
                        }
                    }
                )
            ]

    def paddle_ocr(**kwargs: object) -> FakeEngine:
        initialization_arguments.append(kwargs)
        return FakeEngine()

    monkeypatch.setattr(
        "app.services.ocr_adapters.import_module",
        lambda name: SimpleNamespace(PaddleOCR=paddle_ocr),
    )
    adapter = PaddleOcrAdapter(tmp_path)
    assert initialization_arguments == []
    Image.new("RGB", (120, 80), "white").save(tmp_path / "image.png")

    result = adapter.extract_result(tmp_path / "image.png")

    assert result.text == "First\nSecond"
    assert result.confidence == pytest.approx(0.7)
    assert [line.__dict__ for line in result.line_confidences] == [
        {"line_index": 1, "confidence": 0.8, "text_char_count": 5},
        {"line_index": 2, "confidence": 0.6, "text_char_count": 6},
    ]
    assert all("text" not in line.__dict__ for line in result.line_confidences)
    assert [line.text for line in result.layout_lines] == ["First", "Second"]
    assert result.layout_lines[0].polygon == (
        (10.0, 20.0),
        (90.0, 20.0),
        (90.0, 40.0),
        (10.0, 40.0),
    )
    assert result.image_width == 120
    assert result.image_height == 80
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


def test_missing_and_invalid_scores_do_not_break_text_extraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "text_detection").mkdir()
    (tmp_path / "text_recognition").mkdir()

    class FakeEngine:
        def predict(self, input: str) -> object:
            return [
                SimpleNamespace(
                    json={
                        "res": {
                            "rec_texts": ["First", "Second", "Third", "Fourth"],
                            "rec_scores": ["invalid", 0.75, 2.0],
                        }
                    }
                )
            ]

    monkeypatch.setattr(
        "app.services.ocr_adapters.import_module",
        lambda name: SimpleNamespace(PaddleOCR=lambda **kwargs: FakeEngine()),
    )

    result = PaddleOcrAdapter(tmp_path).extract_result(tmp_path / "image.png")

    assert result.text == "First\nSecond\nThird\nFourth"
    assert result.confidence == 0.75
    assert len(result.line_confidences) == 1
    assert result.line_confidences[0].line_index == 2


def test_absent_scores_produce_null_page_confidence_and_no_line_metrics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "text_detection").mkdir()
    (tmp_path / "text_recognition").mkdir()

    class FakeEngine:
        def predict(self, input: str) -> object:
            return [SimpleNamespace(json={"res": {"rec_texts": ["Still works"]}})]

    monkeypatch.setattr(
        "app.services.ocr_adapters.import_module",
        lambda name: SimpleNamespace(PaddleOCR=lambda **kwargs: FakeEngine()),
    )

    result = PaddleOcrAdapter(tmp_path).extract_result(tmp_path / "image.png")

    assert result.text == "Still works"
    assert result.confidence is None
    assert result.line_confidences == ()


def test_missing_and_invalid_polygons_do_not_break_text_extraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "text_detection").mkdir()
    (tmp_path / "text_recognition").mkdir()

    class FakeEngine:
        def predict(self, input: str) -> object:
            return [
                SimpleNamespace(
                    json={
                        "res": {
                            "rec_texts": ["Invalid polygon", "Missing polygon"],
                            "rec_scores": [0.8, 0.7],
                            "rec_polys": [[[0, 0], [0, 0], [0, 0], [0, 0]]],
                        }
                    }
                )
            ]

    monkeypatch.setattr(
        "app.services.ocr_adapters.import_module",
        lambda name: SimpleNamespace(PaddleOCR=lambda **kwargs: FakeEngine()),
    )

    result = PaddleOcrAdapter(tmp_path).extract_result(tmp_path / "missing.png")

    assert result.text == "Invalid polygon\nMissing polygon"
    assert result.confidence == pytest.approx(0.75)
    assert result.layout_lines == ()


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
