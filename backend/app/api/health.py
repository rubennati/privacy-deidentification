"""Health endpoints. Lightweight; must not affect performance."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.schemas import HealthStatus
from app.services.job_models import JobKind
from app.services.job_store import (
    JobStoreIncompatibleError,
    JobStoreUnavailableError,
    get_job_store,
)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthStatus)
def live() -> HealthStatus:
    """Liveness: the process is up and able to serve requests."""
    return HealthStatus(status="ok")


@router.get("/ready")
def ready(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Readiness: whether persistence is usable and processing can actually proceed.

    Reports per-component states (ADR-0041) instead of a bare flag:

    - ``storage`` — both persistent storage directories exist and are writable;
    - ``job_store`` — the SQLite job database is reachable and schema-compatible (``incompatible``
      names the refusal to touch an unsupported version, distinct from a transient failure);
    - ``ocr_worker`` — in worker mode, whether a live worker heartbeat proves queued OCR jobs will
      actually be processed (``not_applicable`` in sync mode, where OCR runs in-process).

    The endpoint returns ``503`` whenever any applicable component cannot do its job, so "ready"
    genuinely means "requests, persistence, and processing all work right now".
    """
    components = {
        "storage": _storage_state(settings),
        "job_store": _job_store_state(settings),
        "ocr_worker": _ocr_worker_state(settings),
    }
    degraded = [
        name
        for name, state in components.items()
        if state not in ("ok", "not_applicable")
    ]
    body = {
        "status": "ok" if not degraded else "unavailable",
        "components": components,
    }
    return JSONResponse(status_code=200 if not degraded else 503, content=body)


def _storage_state(settings: Settings) -> str:
    storage_directories = (settings.upload_storage_dir, settings.document_data_dir)
    try:
        for directory in storage_directories:
            directory.mkdir(parents=True, exist_ok=True)
        writable = all(os.access(directory, os.W_OK) for directory in storage_directories)
    except OSError:
        writable = False
    return "ok" if writable else "unavailable"


def _job_store_state(settings: Settings) -> str:
    try:
        get_job_store(settings).initialize()
    except JobStoreIncompatibleError:
        return "incompatible"
    except JobStoreUnavailableError:
        return "unavailable"
    return "ok"


def _ocr_worker_state(settings: Settings) -> str:
    """Whether queued OCR work will actually be processed right now."""
    if settings.ocr_execution_mode != "worker":
        return "not_applicable"
    try:
        heartbeat = get_job_store(settings).get_worker_heartbeat(JobKind.OCR_TEXT)
    except (JobStoreIncompatibleError, JobStoreUnavailableError):
        # Reported by the job_store component; do not double-count it here.
        return "unknown"
    if heartbeat is None:
        return "unknown"
    _worker_id, last_seen_at = heartbeat
    try:
        seen = datetime.fromisoformat(last_seen_at.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    age_seconds = (datetime.now(UTC) - seen).total_seconds()
    return "ok" if age_seconds <= settings.ocr_worker_heartbeat_stale_seconds else "stale"
