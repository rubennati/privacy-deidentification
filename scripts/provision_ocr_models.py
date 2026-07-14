"""Provision PaddleOCR inference models for offline, local-only OCR.

Runs inside a throwaway ``python:3.12-slim`` container (see ``fetch-ocr-models.sh`` and the Windows
installer), so the host needs no toolchain — only Docker. Single cross-platform source of truth for
OCR provisioning, invoked identically from ``make ocr-models`` (Linux/macOS) and ``deid.ps1``
(Windows). The backend never downloads at request time; missing models yield a 503.

Environment (all optional; sensible defaults):
    MODELS_ROOT       target root inside the container    (default: /models)
    OCR_MODEL_SOURCE  base download URL                   (default: HuggingFace PaddlePaddle)
    OCR_DET_MODEL     detection model name                (default: PP-OCRv5_mobile_det)
    OCR_REC_MODEL     recognition model name              (default: latin_PP-OCRv5_mobile_rec)
    OCR_FORCE         set to "1" to re-download present models
"""

from __future__ import annotations

import datetime as _dt
import os
import urllib.request
from pathlib import Path

# A PaddleOCR 3.x inference model directory is exactly these three files.
_INFERENCE_FILES = ("inference.json", "inference.pdiparams", "inference.yml")


def _fetch_model(source: str, model: str, target: Path, force: bool) -> None:
    marker = target / ".model"
    if (
        not force
        and (target / "inference.pdiparams").is_file()
        and marker.is_file()
        and marker.read_text(encoding="utf-8").strip() == model
    ):
        print(f"  ✓ {model} already present (skip; set OCR_FORCE=1 to refetch)", flush=True)
        return

    print(f"  → downloading {model}", flush=True)
    target.mkdir(parents=True, exist_ok=True)
    for name in _INFERENCE_FILES:
        url = f"{source}/{model}/resolve/main/{name}"
        tmp = target / f".{name}.part"
        try:
            with urllib.request.urlopen(url) as resp, open(tmp, "wb") as out:
                out.write(resp.read())
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise SystemExit(
                f"error: failed to download {url}: {exc}\n"
                "       check network access to the model source, or set OCR_MODEL_SOURCE."
            ) from exc
        tmp.replace(target / name)
    marker.write_text(f"{model}\n", encoding="utf-8")


def main() -> None:
    models_root = Path(os.environ.get("MODELS_ROOT", "/models"))
    source = os.environ.get("OCR_MODEL_SOURCE", "https://huggingface.co/PaddlePaddle")
    det_model = os.environ.get("OCR_DET_MODEL", "PP-OCRv5_mobile_det")
    rec_model = os.environ.get("OCR_REC_MODEL", "latin_PP-OCRv5_mobile_rec")
    force = os.environ.get("OCR_FORCE", "") == "1"

    print(f"Provisioning OCR models under {models_root} ...", flush=True)
    _fetch_model(source, det_model, models_root / "text_detection", force)
    _fetch_model(source, rec_model, models_root / "text_recognition", force)

    # Provenance only — never commit the model files themselves (see .gitignore: /volumes/*).
    fetched_at = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    (models_root / "MANIFEST.txt").write_text(
        "# Written by scripts/provision_ocr_models.py. Do not commit the model files.\n"
        f"source={source}\n"
        f"text_detection={det_model}\n"
        f"text_recognition={rec_model}\n"
        f"fetched_at={fetched_at}\n",
        encoding="utf-8",
    )

    print(f"✓ OCR models ready: det={det_model} rec={rec_model}", flush=True)


if __name__ == "__main__":
    main()
