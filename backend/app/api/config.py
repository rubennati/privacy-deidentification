"""Public configuration endpoint.

Exposes the effective upload constraints so the browser client mirrors the backend instead of
hardcoding its own copy. The backend remains the single source of truth and the authoritative
enforcement point; this endpoint only lets the UI stay in sync.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.schemas import ConfigResponse, PiiConfigResponse, RuntimeCapabilitiesResponse
from app.services.runtime_capabilities import ocr_runtime_available, pii_runtime_available

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ConfigResponse)
def get_config(settings: Settings = Depends(get_settings)) -> ConfigResponse:
    """Return effective upload constraints plus safe, read-only engine defaults."""
    return ConfigResponse(
        max_upload_bytes=settings.max_upload_bytes,
        allowed_extensions=sorted(settings.allowed_extensions),
        dev_engine_settings_enabled=settings.enable_dev_engine_settings,
        pii=PiiConfigResponse(
            default_profile=settings.effective_pii_profile,
            available_profiles=list(settings.supported_pii_profiles),
            candidate_validation_enabled=settings.pii_candidate_validation_enabled,
            score_threshold=settings.pii_score_threshold,
        ),
        runtime=RuntimeCapabilitiesResponse(
            ocr_available=ocr_runtime_available(settings),
            pii_available=pii_runtime_available(settings),
        ),
    )
