"""Check the simplified Phase 3.6 runtime surface.

This is a lightweight guard for repository-owned runtime files. It deliberately avoids importing
application code or parsing private data; the full rendered Compose validation still happens with
``docker compose config`` during release checks.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _service_block(compose: str, service: str) -> str:
    match = re.search(rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  \S|\Z)", compose)
    _require(match is not None, f"docker-compose.yml must define {service}")
    return match.group(1)


def _has_active_setting(env_example: str, key: str) -> bool:
    """True if ``key=`` appears as an active (uncommented) .env.example line."""
    return re.search(rf"(?m)^{re.escape(key)}=", env_example) is not None


def main() -> None:
    compose = _read("docker-compose.yml")
    makefile = _read("Makefile")
    env_example = _read(".env.example")
    nginx = _read("frontend/nginx.conf")
    gitignore = _read(".gitignore")

    api_block = _service_block(compose, "api")
    worker_block = _service_block(compose, "ocr-worker")
    _service_block(compose, "frontend")
    _require("profiles:" not in compose, "default stack must not require Compose profiles")
    _require("build:" in api_block, "api must own the shared backend image build")
    _require("build:" not in worker_block, "ocr-worker must reuse the api image without rebuilding")
    _require(
        "image: privacy-deidentification-api:0.1.0" in worker_block,
        "ocr-worker must use the shared api image",
    )
    _require(
        "OCR_EXECUTION_MODE: ${OCR_EXECUTION_MODE:-worker}" in compose,
        "Compose must default OCR_EXECUTION_MODE to worker",
    )
    _require(
        "INSTALL_OCR" not in compose and "INSTALL_PII" not in compose,
        "Compose must not expose OCR/PII install build toggles",
    )
    # DATA_ROOT is the single user-facing storage knob; internal paths are mapped from it, and the
    # SQLite job DB lives in its own job-state root (never beside per-document artifacts).
    _require("${DATA_ROOT:-./volumes}" in compose, "Compose must map host storage from DATA_ROOT")
    _require(
        "DATA_JOB_STATE_DIR: ${DATA_JOB_STATE_DIR:-/data/job-state}" in compose,
        "Compose must define the dedicated job-state directory",
    )
    _require("/document-store:" in compose, "Compose must mount the document-store volume")
    _require("/job-state:" in compose, "Compose must mount the dedicated job-state volume")
    _require(
        "/data/document-data" not in compose,
        "Compose must not reference the retired document-data path",
    )
    _require("proxy_pass http://api:8000;" in nginx, "nginx must proxy to the api service")

    removed_targets = (
        "up-pii:",
        "up-ocr:",
        "up-full:",
        "up-ocr-worker:",
        "up-full-worker:",
        "build-pii:",
        "build-ocr:",
        "build-full:",
        "bf:",
        "docker-prune:",
        "docker-prune-project:",
        "dev-rebuild:",
    )
    for target in removed_targets:
        _require(target not in makefile, f"Makefile must not expose removed target {target}")
    _require("docker system prune" not in makefile, "Makefile must not call docker system prune")

    _require(
        "COMPOSE_PROJECT_NAME=privacy-deidentification" in env_example,
        ".env.example must document the default project name",
    )
    _require(
        "OCR_EXECUTION_MODE=worker" in env_example,
        ".env.example must default to worker OCR mode",
    )
    _require(
        "INSTALL_OCR" not in env_example and "INSTALL_PII" not in env_example,
        ".env.example must not expose install toggles",
    )
    # Environment simplification: users configure a single DATA_ROOT; container-internal storage
    # paths must not be presented as normal, active deployment settings (they can silently split
    # API/worker storage). They may still appear commented as advanced overrides.
    _require(
        _has_active_setting(env_example, "DATA_ROOT"),
        ".env.example must expose DATA_ROOT as the single storage knob",
    )
    for internal_path_key in (
        "UPLOAD_STORAGE_DIR",
        "DOCUMENT_DATA_DIR",
        "DATA_JOB_STATE_DIR",
        "JOB_STORE_DB_PATH",
        "PII_FEEDBACK_ARCHIVE_DIR",
        "OCR_MODEL_DIR",
    ):
        _require(
            not _has_active_setting(env_example, internal_path_key),
            f".env.example must not expose internal path {internal_path_key} as an active setting",
        )
    _require(
        "document-data" not in env_example,
        ".env.example must not reference the retired document-data path",
    )

    for pattern in ("*.sqlite3", "*.sqlite3-shm", "*.sqlite3-wal", "/volumes/*"):
        _require(pattern in gitignore, f".gitignore must include {pattern}")


if __name__ == "__main__":
    main()
