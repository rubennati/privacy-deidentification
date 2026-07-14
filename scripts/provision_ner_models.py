"""Provision the GLiNER NER model + backbone for fully offline, local-only inference.

Runs inside a throwaway ``python:3.12-slim`` container (see ``fetch-ner-models.sh`` and the Windows
installer), so the host needs no Python/huggingface_hub toolchain — only Docker. It is the single
cross-platform source of truth for NER provisioning, invoked identically from ``make ner-models``
(Linux/macOS) and ``deid.ps1`` (Windows).

GLiNER (``urchade/gliner_multi-v2.1``) ships only the span head and references its transformer
backbone (``microsoft/mdeberta-v3-base``) by HuggingFace id. With only the head present, GLiNER
fetches the backbone from the internet on first load — which the api/ocr-worker network
(``internal: true``, no egress) blocks, so PII analysis fails with 503. This provisions BOTH and
rewrites the head's ``model_name`` to the container-local backbone path, so nothing is fetched at
runtime. Idempotent: re-downloads only changed files and re-applies the rewrite. See ADR-0042.

Environment (all optional; sensible defaults):
    MODELS_ROOT        target root inside the container   (default: /models)
    GLINER_MODEL       GLiNER head HuggingFace id         (default: urchade/gliner_multi-v2.1)
    GLINER_BACKBONE    backbone HuggingFace id            (default: microsoft/mdeberta-v3-base)
    CONTAINER_NER_DIR  where MODELS_ROOT mounts in the api/worker (default: /models/ner)
"""

from __future__ import annotations

import json
import os

from huggingface_hub import snapshot_download

_BACKBONE_PATTERNS = [
    "config.json",
    "pytorch_model.bin",
    "model.safetensors",
    "tokenizer_config.json",
    "tokenizer.json",
    "spm.model",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
]


def main() -> None:
    models_root = os.environ.get("MODELS_ROOT", "/models")
    head_id = os.environ.get("GLINER_MODEL", "urchade/gliner_multi-v2.1")
    backbone_id = os.environ.get("GLINER_BACKBONE", "microsoft/mdeberta-v3-base")
    container_ner_dir = os.environ.get("CONTAINER_NER_DIR", "/models/ner")

    head_name = head_id.rsplit("/", 1)[-1]
    backbone_name = backbone_id.rsplit("/", 1)[-1]

    print(f"Provisioning GLiNER head     {head_id} -> {models_root}/{head_name}", flush=True)
    head_dir = snapshot_download(head_id, local_dir=f"{models_root}/{head_name}")

    print(f"Provisioning backbone {backbone_id} -> {models_root}/{backbone_name}", flush=True)
    snapshot_download(
        backbone_id,
        local_dir=f"{models_root}/{backbone_name}",
        allow_patterns=_BACKBONE_PATTERNS,
    )

    # Point the head at the local backbone path (as seen inside the api/ocr-worker containers) so
    # GLiNER never resolves the backbone by its HuggingFace id at runtime.
    cfg_path = os.path.join(head_dir, "gliner_config.json")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["model_name"] = f"{container_ner_dir}/{backbone_name}"
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)

    print(f"rewrote gliner_config.json model_name -> {cfg['model_name']}", flush=True)
    print(f"GLiNER model + backbone provisioned under {models_root}", flush=True)


if __name__ == "__main__":
    main()
