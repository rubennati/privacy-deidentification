"""Public configuration endpoint.

Exposes the effective upload constraints so the browser client mirrors the backend instead of
hardcoding its own copy. The backend remains the single source of truth and the authoritative
enforcement point; this endpoint only lets the UI stay in sync.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.schemas import ConfigResponse

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ConfigResponse)
def get_config(settings: Settings = Depends(get_settings)) -> ConfigResponse:
    """Return the effective upload constraints (size limit and allowed extensions)."""
    return ConfigResponse(
        max_upload_bytes=settings.max_upload_bytes,
        allowed_extensions=sorted(settings.allowed_extensions),
    )
