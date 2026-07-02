"""OCR adapter boundary with a lazily loaded PaddleOCR implementation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from math import isfinite
from numbers import Real
from pathlib import Path
from threading import Lock
from typing import Protocol, cast, runtime_checkable

from app.errors import ApiError


class OcrAdapter(Protocol):
    """Extract text from one raster image."""

    def extract_text(self, image_path: Path) -> str: ...

    def tool_versions(self) -> dict[str, str]: ...


@dataclass(frozen=True)
class OcrLineMetric:
    """Confidence-only metadata for one recognized line; never carries its raw text."""

    line_index: int
    confidence: float
    text_char_count: int


@dataclass(frozen=True)
class OcrExtractionResult:
    """Canonical OCR text plus additive engine-reported confidence metrics."""

    text: str
    confidence: float | None = None
    line_confidences: tuple[OcrLineMetric, ...] = ()


@runtime_checkable
class ConfidenceReportingOcrAdapter(Protocol):
    """Optional adapter extension; callers retain support for legacy text-only adapters."""

    def extract_result(self, image_path: Path) -> OcrExtractionResult: ...


class _PaddleEngine(Protocol):
    def predict(self, input: str) -> object: ...


class OcrUnavailableError(ApiError):
    """Raised when the configured OCR engine cannot be imported or initialized."""

    def __init__(self) -> None:
        super().__init__("PaddleOCR is not available.", 503)


class PaddleOcrAdapter:
    """CPU-only PaddleOCR adapter; imports and model initialization are lazy."""

    def __init__(
        self,
        model_dir: Path | None,
        detection_model_name: str | None = None,
        recognition_model_name: str | None = None,
    ) -> None:
        self._model_dir = model_dir
        self._detection_model_name = detection_model_name
        self._recognition_model_name = recognition_model_name
        self._engine: _PaddleEngine | None = None
        self._lock = Lock()

    def extract_text(self, image_path: Path) -> str:
        """Retain the original text-only adapter API for compatibility."""
        return self.extract_result(image_path).text

    def extract_result(self, image_path: Path) -> OcrExtractionResult:
        results = self._get_engine().predict(input=str(image_path))
        return _extract_result(results)

    def tool_versions(self) -> dict[str, str]:
        versions: dict[str, str] = {}
        for package in ("paddleocr", "paddlepaddle"):
            try:
                versions[package] = version(package)
            except PackageNotFoundError:
                continue
        return versions

    def _get_engine(self) -> _PaddleEngine:
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is not None:
                return self._engine
            detection_model_dir, recognition_model_dir = self._local_model_directories()
            # PaddleOCR 3.x infers the model name as its default when only a directory is given, so
            # a non-default local model (e.g. the Latin recognizer) is rejected with a name
            # mismatch unless the matching name is passed explicitly alongside the directory.
            engine_kwargs: dict[str, object] = {
                "device": "cpu",
                # PaddlePaddle 3.x enables MKL-DNN (oneDNN) for CPU inference by default, but the
                # oneDNN + PIR path raises "ConvertPirAttribute2RuntimeAttribute not support" on
                # the PP-OCRv5 models. Disable it so CPU inference runs (a bit slower, but stable).
                "enable_mkldnn": False,
                "text_detection_model_dir": str(detection_model_dir),
                "text_recognition_model_dir": str(recognition_model_dir),
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
            }
            if self._detection_model_name is not None:
                engine_kwargs["text_detection_model_name"] = self._detection_model_name
            if self._recognition_model_name is not None:
                engine_kwargs["text_recognition_model_name"] = self._recognition_model_name
            try:
                module = import_module("paddleocr")
                paddle_ocr = module.PaddleOCR
                engine = paddle_ocr(**engine_kwargs)
            except Exception as exc:
                raise OcrUnavailableError from exc
            self._engine = cast(_PaddleEngine, engine)
            return self._engine

    def _local_model_directories(self) -> tuple[Path, Path]:
        if self._model_dir is None:
            raise OcrUnavailableError
        detection_model_dir = self._model_dir / "text_detection"
        recognition_model_dir = self._model_dir / "text_recognition"
        if not detection_model_dir.is_dir() or not recognition_model_dir.is_dir():
            raise OcrUnavailableError
        return detection_model_dir, recognition_model_dir


@lru_cache
def get_ocr_adapter(
    model_dir: str | None = None,
    detection_model_name: str | None = None,
    recognition_model_name: str | None = None,
) -> OcrAdapter:
    """Provide one lazy adapter per configured local model root and model names."""
    return PaddleOcrAdapter(
        Path(model_dir) if model_dir is not None else None,
        detection_model_name,
        recognition_model_name,
    )


def extract_ocr_result(ocr_adapter: OcrAdapter, image_path: Path) -> OcrExtractionResult:
    """Extract OCR text and metrics, falling back cleanly for legacy text-only adapters."""
    if isinstance(ocr_adapter, ConfidenceReportingOcrAdapter):
        return ocr_adapter.extract_result(image_path)
    return OcrExtractionResult(text=ocr_adapter.extract_text(image_path))


def _extract_result(results: object) -> OcrExtractionResult:
    texts: list[str] = []
    line_confidences: list[OcrLineMetric] = []
    for result in _as_sequence(results):
        payload = getattr(result, "json", result)
        if callable(payload):
            payload = payload()
        if isinstance(payload, Mapping):
            result_payload = payload.get("res", payload)
            if isinstance(result_payload, Mapping):
                recognized = result_payload.get("rec_texts", [])
                scores = _as_sequence(result_payload.get("rec_scores", []))
                for payload_index, text in enumerate(_as_sequence(recognized)):
                    if isinstance(text, str) and text:
                        texts.append(text)
                        score = _valid_confidence(
                            scores[payload_index] if payload_index < len(scores) else None
                        )
                        if score is not None:
                            line_confidences.append(
                                OcrLineMetric(
                                    line_index=len(texts),
                                    confidence=score,
                                    text_char_count=len(text),
                                )
                            )
    confidence = (
        sum(line.confidence for line in line_confidences) / len(line_confidences)
        if line_confidences
        else None
    )
    return OcrExtractionResult(
        text="\n".join(texts),
        confidence=confidence,
        line_confidences=tuple(line_confidences),
    )


def _valid_confidence(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    confidence = float(value)
    if not isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        return None
    return confidence


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return [value]
