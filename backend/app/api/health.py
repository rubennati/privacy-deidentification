"""Health endpoints. Lightweight; must not affect performance."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.schemas import HealthStatus

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthStatus)
def live() -> HealthStatus:
    """Liveness: the process is up and able to serve requests."""
    return HealthStatus(status="ok")


@router.get("/ready")
def ready(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Readiness: the upload directory exists and is writable."""
    upload_dir = settings.upload_dir
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        writable = os.access(upload_dir, os.W_OK)
    except OSError:
        writable = False

    if not writable:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ok"})
