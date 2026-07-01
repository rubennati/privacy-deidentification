#!/bin/sh
# Provision PaddleOCR models into volumes/ocr-models/{text_detection,text_recognition}.
#
# Idempotent and offline-at-runtime: run this once before building/using the OCR runtime. The
# backend never downloads models during a request; it returns 503 when they are missing.
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
MODEL_SOURCE="${OCR_MODEL_SOURCE:-https://huggingface.co/PaddlePaddle}"
DET_MODEL="${OCR_DET_MODEL:-PP-OCRv5_mobile_det}"
REC_MODEL="${OCR_REC_MODEL:-latin_PP-OCRv5_mobile_rec}"

# A PaddleOCR 3.x inference model directory is exactly these three files.
INFERENCE_FILES="inference.json inference.pdiparams inference.yml"

FORCE=0
if [ "${1:-}" = "--force" ]; then
    FORCE=1
elif [ "${1:-}" != "" ]; then
    echo "error: unknown argument '$1' (only --force is supported)" >&2
    exit 2
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "error: 'curl' is required but was not found on PATH." >&2
    exit 1
fi

fetch_model() {
    model="$1"
    target="$2"
    marker="$target/.model"

    if [ "$FORCE" -eq 0 ] \
        && [ -f "$target/inference.pdiparams" ] \
        && [ -f "$marker" ] \
        && [ "$(cat "$marker")" = "$model" ]; then
        echo "  ✓ $model already present in ${target#"$REPO_ROOT"/} (skip; --force to refetch)"
        return 0
    fi

    echo "  → downloading $model into ${target#"$REPO_ROOT"/}"
    mkdir -p "$target"
    for file in $INFERENCE_FILES; do
        url="$MODEL_SOURCE/$model/resolve/main/$file"
        tmp="$target/.$file.part"
        if ! curl -fSL --retry 3 --retry-delay 2 -o "$tmp" "$url"; then
            rm -f "$tmp"
            echo "error: failed to download $url" >&2
            echo "       check network access to the model source, or set OCR_MODEL_SOURCE." >&2
            exit 1
        fi
        mv "$tmp" "$target/$file"
    done
    printf '%s\n' "$model" >"$marker"
}

echo "Provisioning OCR models under ${MODELS_DIR#"$REPO_ROOT"/} ..."
fetch_model "$DET_MODEL" "$MODELS_DIR/text_detection"
fetch_model "$REC_MODEL" "$MODELS_DIR/text_recognition"

# Provenance only — never commit the model files themselves (see .gitignore: /volumes/*).
cat >"$MODELS_DIR/MANIFEST.txt" <<EOF
# Written by scripts/fetch-ocr-models.sh. Do not commit the model files.
source=$MODEL_SOURCE
text_detection=$DET_MODEL
text_recognition=$REC_MODEL
fetched_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

echo "✓ OCR models ready:"
echo "    text_detection   = $DET_MODEL"
echo "    text_recognition = $REC_MODEL"
echo "  Set OCR_MODEL_DIR=/models/ocr and build the OCR runtime (make build-ocr / make up-ocr)."
