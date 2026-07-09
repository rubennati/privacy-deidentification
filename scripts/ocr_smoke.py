"""Smoke-test the real PaddleOCR runtime against locally provisioned models.

Deliberately not part of ``make test``: it needs the OCR image extra, platform-compatible
PaddlePaddle wheels, and model files under ``OCR_MODEL_DIR``. Run via ``make ocr-smoke``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.config import get_settings
from app.services.ocr_adapters import OcrUnavailableError, PaddleOcrAdapter

_SAMPLE_TEXT = "OCR Smoke 2026"


def _render_sample(path: Path) -> None:
    image = Image.new("RGB", (520, 110), "white")
    try:
        font = ImageFont.load_default(size=52)
    except TypeError:  # Pillow < 10 has no size argument
        font = ImageFont.load_default()
    ImageDraw.Draw(image).text((14, 26), _SAMPLE_TEXT, fill="black", font=font)
    image.save(path)


def main() -> int:
    settings = get_settings()
    if settings.ocr_model_dir is None:
        print("FAIL: OCR_MODEL_DIR is not set. Run `make ocr-models` and set OCR_MODEL_DIR.")
        return 1

    image_path = Path("/tmp/ocr-smoke.png")
    _render_sample(image_path)

    adapter = PaddleOcrAdapter(
        Path(settings.ocr_model_dir),
        settings.ocr_detection_model_name,
        settings.ocr_recognition_model_name,
    )
    try:
        text = adapter.extract_text(image_path)
    except OcrUnavailableError:
        print(
            "FAIL: OCR runtime unavailable — models missing under "
            f"{settings.ocr_model_dir} or the OCR packages are not installed. "
            "Run `make ocr-models` and rebuild the default runtime image."
        )
        return 1

    print(f"rendered: {_SAMPLE_TEXT!r}")
    print(f"recognized: {text!r}")
    if not text.strip():
        print("FAIL: OCR returned no text.")
        return 1
    print("OK: OCR runtime recognized text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
