"""OCR adapter boundary with a lazily loaded PaddleOCR implementation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import Lock
from typing import Protocol, cast

from app.errors import ApiError


class OcrAdapter(Protocol):
    """Extract text from one raster image."""

    def extract_text(self, image_path: Path) -> str: ...

    def tool_versions(self) -> dict[str, str]: ...


class _PaddleEngine(Protocol):
    def predict(self, input: str) -> object: ...


class OcrUnavailableError(ApiError):
    """Raised when the configured OCR engine cannot be imported or initialized."""

    def __init__(self) -> None:
        super().__init__("PaddleOCR is not available.", 503)


class PaddleOcrAdapter:
    """CPU-only PaddleOCR adapter; imports and model initialization are lazy."""

    def __init__(self) -> None:
        self._engine: _PaddleEngine | None = None
        self._lock = Lock()

    def extract_text(self, image_path: Path) -> str:
        results = self._get_engine().predict(input=str(image_path))
        return "\n".join(_extract_recognized_texts(results))

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
            try:
                module = import_module("paddleocr")
                paddle_ocr = module.PaddleOCR
                engine = paddle_ocr(
                    device="cpu",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
            except Exception as exc:
                raise OcrUnavailableError from exc
            self._engine = cast(_PaddleEngine, engine)
            return self._engine


@lru_cache
def get_ocr_adapter() -> OcrAdapter:
    """Provide one lazily initialized adapter instance to FastAPI."""
    return PaddleOcrAdapter()


def _extract_recognized_texts(results: object) -> list[str]:
    texts: list[str] = []
    for result in _as_sequence(results):
        payload = getattr(result, "json", result)
        if callable(payload):
            payload = payload()
        if isinstance(payload, Mapping):
            result_payload = payload.get("res", payload)
            if isinstance(result_payload, Mapping):
                recognized = result_payload.get("rec_texts", [])
                for text in _as_sequence(recognized):
                    if isinstance(text, str) and text:
                        texts.append(text)
    return texts


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return [value]
