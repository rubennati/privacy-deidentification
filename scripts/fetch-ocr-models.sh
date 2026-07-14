#!/bin/sh
# Provision PaddleOCR models into volumes/ocr-models/{text_detection,text_recognition}. Thin wrapper
# around scripts/provision_ocr_models.py (the single cross-platform provisioning logic, shared with
# the Windows installer) run inside a throwaway python:3.12-slim container, so the host needs no
# toolchain — only Docker.
#
# Idempotent and offline-at-runtime: run once before building/using the OCR runtime. The backend
# never downloads models during a request; it returns 503 when they are missing.
#
# Defaults (overridable via environment):
#   OCR_MODELS_DIR    target root            (default: <repo>/volumes/ocr-models)
#   OCR_DET_MODEL     detection model name   (default: PP-OCRv5_mobile_det)
#   OCR_REC_MODEL     recognition model name (default: latin_PP-OCRv5_mobile_rec — German/Latin)
#   OCR_MODEL_SOURCE  base download URL      (default: https://huggingface.co/PaddlePaddle)
#
# Usage:  scripts/fetch-ocr-models.sh [--force]
set -eu

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
MODELS_DIR="${OCR_MODELS_DIR:-$REPO_ROOT/volumes/ocr-models}"

OCR_FORCE=""
if [ "${1:-}" = "--force" ]; then
    OCR_FORCE=1
elif [ "${1:-}" != "" ]; then
    echo "error: unknown argument '$1' (only --force is supported)" >&2
    exit 2
fi

mkdir -p "$MODELS_DIR"

docker run --rm \
  -e MODELS_ROOT=/models \
  -e OCR_MODEL_SOURCE="${OCR_MODEL_SOURCE:-https://huggingface.co/PaddlePaddle}" \
  -e OCR_DET_MODEL="${OCR_DET_MODEL:-PP-OCRv5_mobile_det}" \
  -e OCR_REC_MODEL="${OCR_REC_MODEL:-latin_PP-OCRv5_mobile_rec}" \
  -e OCR_FORCE="$OCR_FORCE" \
  -v "$MODELS_DIR":/models \
  -v "$REPO_ROOT/scripts":/work:ro \
  python:3.12-slim python /work/provision_ocr_models.py

echo "✓ OCR models ready under ${MODELS_DIR#"$REPO_ROOT"/}"
echo "  Start the default stack with make up."
