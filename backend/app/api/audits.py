"""Synchronous Audit v1 endpoints for uploaded documents."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.config import Settings, get_settings
from app.schemas import AuditArtifact, ErrorResponse
from app.services.audit_service import create_audit, get_latest_audit

router = APIRouter(prefix="/documents", tags=["audits"])


@router.post(
    "/{document_id}/audit",
    response_model=AuditArtifact,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def audit_document(
    document_id: str, settings: Settings = Depends(get_settings)
) -> AuditArtifact:
    """Analyze a verified original and persist an immutable audit result."""
    return create_audit(settings, document_id)


@router.get(
    "/{document_id}/audit",
    response_model=AuditArtifact,
    responses={404: {"model": ErrorResponse}},
)
def get_document_audit(
    document_id: str, settings: Settings = Depends(get_settings)
) -> AuditArtifact:
    """Return the newest audit result for a document."""
    return get_latest_audit(settings, document_id)
