#!/bin/sh
# Provision the GLiNER NER model AND its transformer backbone into volumes/ner-models for fully
# offline, local-only inference. Thin wrapper around scripts/provision_ner_models.py (the single
# cross-platform provisioning logic, shared with the Windows installer) run inside a throwaway
# python:3.12-slim container, so the host needs no Python/huggingface_hub toolchain — only Docker.
#
# GLiNER (urchade/gliner_multi-v2.1) ships only the span head and references its backbone
# (microsoft/mdeberta-v3-base) by HuggingFace id. Provisioning only the head makes GLiNER fetch the
# backbone at runtime, which the api/ocr-worker network (internal: true, no egress) blocks — so PII
# analysis fails with 503. This provisions BOTH and rewrites the head's model_name to the local
# backbone path, so nothing is fetched at runtime. Inference is fully local. See ADR-0042.
#
# Idempotent: safe to re-run (re-downloads only changed files, re-applies the config rewrite).
#
# Defaults (overridable via environment):
#   NER_MODELS_DIR   target root          (default: <repo>/volumes/ner-models)
#   GLINER_MODEL     GLiNER head HF id    (default: urchade/gliner_multi-v2.1)
#   GLINER_BACKBONE  backbone HF id       (default: microsoft/mdeberta-v3-base — gliner_multi backbone)
#   GLINER_MODEL_DIR container mount path (default: /models/ner — where NER_MODELS_DIR mounts read-only)
#
# Usage:  scripts/fetch-ner-models.sh
set -eu

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
MODELS_DIR="${NER_MODELS_DIR:-$REPO_ROOT/volumes/ner-models}"

mkdir -p "$MODELS_DIR"

# Mount the models target at /models and the scripts dir at /work; run the shared provisioning
# script. All tuning is passed through as environment variables it understands.
docker run --rm \
  -e MODELS_ROOT=/models \
  -e GLINER_MODEL="${GLINER_MODEL:-urchade/gliner_multi-v2.1}" \
  -e GLINER_BACKBONE="${GLINER_BACKBONE:-microsoft/mdeberta-v3-base}" \
  -e CONTAINER_NER_DIR="${GLINER_MODEL_DIR:-/models/ner}" \
  -v "$MODELS_DIR":/models \
  -v "$REPO_ROOT/scripts":/work:ro \
  python:3.12-slim sh -lc 'pip install --quiet huggingface_hub && python /work/provision_ner_models.py'

echo "✓ NER models ready under ${MODELS_DIR#"$REPO_ROOT"/}"
