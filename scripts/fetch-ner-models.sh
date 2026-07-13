#!/bin/sh
# Provision the GLiNER NER model into volumes/ner-models/<model> for offline, local-only inference.
#
# Mirrors scripts/fetch-ocr-models.sh: run this once before building/using the `gliner` NER backend
# (PII_NER_BACKEND=gliner). The backend never downloads models during a request; it returns 503 when
# the model is missing. GLiNER inference itself is fully local — nothing leaves the machine. The
# model is mounted read-only into the api/ocr-worker containers at GLINER_MODEL_DIR. See ADR-0042.
#
# Defaults (overridable via environment):
#   NER_MODELS_DIR   target root      (default: <repo>/volumes/ner-models)
#   GLINER_MODEL     HuggingFace id   (default: urchade/gliner_multi-v2.1)
#
# Usage:  scripts/fetch-ner-models.sh
set -eu

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
MODELS_DIR="${NER_MODELS_DIR:-$REPO_ROOT/volumes/ner-models}"
GLINER_MODEL="${GLINER_MODEL:-urchade/gliner_multi-v2.1}"
TARGET_NAME="$(basename "$GLINER_MODEL")"

mkdir -p "$MODELS_DIR"
echo "Provisioning $GLINER_MODEL -> $MODELS_DIR/$TARGET_NAME"

# Download inside a throwaway container so the host needs no Python/huggingface_hub toolchain.
docker run --rm -v "$MODELS_DIR":/models python:3.12-slim sh -lc \
  "pip install --quiet huggingface_hub && python -c \"
from huggingface_hub import snapshot_download
snapshot_download('$GLINER_MODEL', local_dir='/models/$TARGET_NAME')
print('done')
\""

echo "Model provisioned at $MODELS_DIR/$TARGET_NAME"
