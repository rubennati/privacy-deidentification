#!/bin/sh
# Provision the GLiNER NER model AND its transformer backbone into volumes/ner-models for fully
# offline, local-only inference.
#
# GLiNER (urchade/gliner_multi-v2.1) ships only the span head. It references a separate transformer
# backbone (microsoft/mdeberta-v3-base) by HuggingFace id in gliner_config.json ("model_name"). If
# only the head is provisioned, GLiNER tries to fetch that backbone from the internet on first load —
# which the api/ocr-worker network (internal: true, no egress) correctly blocks, so PII analysis
# fails with 503. This script provisions BOTH and rewrites the head's model_name to the local backbone
# path, so nothing is fetched at runtime. Mirrors scripts/fetch-ocr-models.sh; run once before using
# PII_NER_BACKEND=gliner. Inference is fully local — no document text ever leaves the machine. See
# ADR-0042.
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
GLINER_MODEL="${GLINER_MODEL:-urchade/gliner_multi-v2.1}"
GLINER_BACKBONE="${GLINER_BACKBONE:-microsoft/mdeberta-v3-base}"
CONTAINER_NER_DIR="${GLINER_MODEL_DIR:-/models/ner}"
HEAD_NAME="$(basename "$GLINER_MODEL")"
BACKBONE_NAME="$(basename "$GLINER_BACKBONE")"

mkdir -p "$MODELS_DIR"
echo "Provisioning GLiNER head     $GLINER_MODEL     -> $MODELS_DIR/$HEAD_NAME"
echo "Provisioning GLiNER backbone $GLINER_BACKBONE -> $MODELS_DIR/$BACKBONE_NAME"

# Download inside a throwaway container so the host needs no Python/huggingface_hub toolchain. The
# provisioning script is fed on stdin (python -) with all values passed as env vars, so there is no
# fragile nested shell quoting. The head config's "model_name" is rewritten to the container-local
# backbone path, so at runtime transformers loads the backbone from disk rather than by its HF id.
docker run --rm -i \
  -e HEAD_NAME="$HEAD_NAME" \
  -e BACKBONE_NAME="$BACKBONE_NAME" \
  -e GLINER_MODEL="$GLINER_MODEL" \
  -e GLINER_BACKBONE="$GLINER_BACKBONE" \
  -e CONTAINER_NER_DIR="$CONTAINER_NER_DIR" \
  -v "$MODELS_DIR":/models \
  python:3.12-slim sh -lc 'pip install --quiet huggingface_hub && python -' <<'PYEOF'
import json
import os

from huggingface_hub import snapshot_download

head_dir = snapshot_download(os.environ["GLINER_MODEL"], local_dir=f"/models/{os.environ['HEAD_NAME']}")
snapshot_download(
    os.environ["GLINER_BACKBONE"],
    local_dir=f"/models/{os.environ['BACKBONE_NAME']}",
    allow_patterns=[
        "config.json", "pytorch_model.bin", "model.safetensors",
        "tokenizer_config.json", "tokenizer.json", "spm.model",
        "sentencepiece.bpe.model", "special_tokens_map.json",
    ],
)

# Point the head at the local backbone path (as seen inside the api/ocr-worker containers) so GLiNER
# never resolves the backbone by its HuggingFace id at runtime.
cfg_path = os.path.join(head_dir, "gliner_config.json")
with open(cfg_path) as fh:
    cfg = json.load(fh)
cfg["model_name"] = f"{os.environ['CONTAINER_NER_DIR']}/{os.environ['BACKBONE_NAME']}"
with open(cfg_path, "w") as fh:
    json.dump(cfg, fh, indent=2)
print("rewrote gliner_config.json model_name ->", cfg["model_name"])
PYEOF

echo "GLiNER model + backbone provisioned at $MODELS_DIR (head points at $CONTAINER_NER_DIR/$BACKBONE_NAME)"
