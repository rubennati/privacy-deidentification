"""Synchronous PII Workstation v1 endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.config import Settings, get_settings
from app.schemas import ErrorResponse, PiiArtifact
from app.services.pii_adapters import PiiAnalyzer, get_pii_analyzer
from app.services.pii_service import create_pii_artifact, get_latest_pii

router = APIRouter(prefix="/documents", tags=["pii"])


def provide_pii_analyzer(settings: Settings = Depends(get_settings)) -> PiiAnalyzer:
    """Bind the configured single language and local spaCy package to the adapter."""
    return get_pii_analyzer(settings.pii_language, settings.pii_spacy_model)


@router.post(
    "/{document_id}/pii",
    response_model=PiiArtifact,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def analyze_document_pii(
    document_id: str,
    settings: Settings = Depends(get_settings),
    analyzer: PiiAnalyzer = Depends(provide_pii_analyzer),
) -> PiiArtifact:
    """Detect PII in the latest valid text result and persist an immutable result."""
    return create_pii_artifact(settings, document_id, analyzer)


@router.get(
    "/{document_id}/pii",
    response_model=PiiArtifact,
    responses={404: {"model": ErrorResponse}},
)
def get_document_pii(
    document_id: str, settings: Settings = Depends(get_settings)
) -> PiiArtifact:
    """Return the newest PII result for a document."""
    return get_latest_pii(settings, document_id)
