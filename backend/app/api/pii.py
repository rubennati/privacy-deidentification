"""Synchronous PII Workstation v1 endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, status

from app.config import Settings, get_settings
from app.schemas import (
    ErrorResponse,
    PiiArtifact,
    PiiFeedbackAck,
    PiiFeedbackRequest,
    PiiFeedbackSummary,
    PiiReviewDecisionAck,
    PiiReviewDecisionRequest,
    PiiReviewResult,
    PiiRunRequest,
)
from app.services.feedback_service import record_pii_feedback, summarize_pii_feedback
from app.services.job_models import JobContext, JobKind
from app.services.job_runner import SyncJobRunner, get_job_runner
from app.services.pii_adapters import PiiAnalyzer, get_pii_analyzer
from app.services.pii_review_service import get_pii_review_result, set_pii_review_decision
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
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def analyze_document_pii(
    document_id: str,
    request: PiiRunRequest | None = Body(default=None),
    settings: Settings = Depends(get_settings),
    analyzer: PiiAnalyzer = Depends(provide_pii_analyzer),
    runner: SyncJobRunner = Depends(get_job_runner),
) -> PiiArtifact:
    """Detect PII in the latest valid text result and persist an immutable result.

    Detection runs through the internal job abstraction (ADR-0023 Phase 1); execution is still
    synchronous and in-process, so the request/response and error semantics are unchanged. PII still
    uses the technical raw text as authoritative input.
    """
    context = JobContext.create(
        kind=JobKind.PII_DETECTION,
        document_id=document_id,
        execution_mode=runner.execution_mode,
    )
    result = runner.run(
        context,
        lambda: create_pii_artifact(settings, document_id, analyzer, request),
    )
    return result.unwrap()


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


@router.post(
    "/{document_id}/pii/feedback",
    response_model=PiiFeedbackAck,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def submit_pii_feedback(
    document_id: str,
    request: PiiFeedbackRequest = Body(...),
    settings: Settings = Depends(get_settings),
) -> PiiFeedbackAck:
    """Append dev-only review feedback for one detected PII entity (gated; 403 when disabled)."""
    return record_pii_feedback(settings, document_id, request)


@router.get(
    "/{document_id}/pii/feedback",
    response_model=PiiFeedbackSummary,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def get_pii_feedback_summary(
    document_id: str,
    artifact_id: str = Query(..., pattern=r"^[0-9a-f]{32}$"),
    settings: Settings = Depends(get_settings),
) -> PiiFeedbackSummary:
    """Return the latest dev-only feedback per entity for one PII artifact (gated; 403 off)."""
    return summarize_pii_feedback(settings, document_id, artifact_id)


@router.get(
    "/{document_id}/pii/review",
    response_model=PiiReviewResult,
    responses={404: {"model": ErrorResponse}},
)
def get_document_pii_review(
    document_id: str, settings: Settings = Depends(get_settings)
) -> PiiReviewResult:
    """Return reviewable entity groups and occurrences for the document's latest PII result."""
    return get_pii_review_result(settings, document_id)


@router.post(
    "/{document_id}/pii/review/decisions",
    response_model=PiiReviewDecisionAck,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def submit_pii_review_decision(
    document_id: str,
    request: PiiReviewDecisionRequest = Body(...),
    settings: Settings = Depends(get_settings),
) -> PiiReviewDecisionAck:
    """Record a group- or occurrence-level review decision."""
    return set_pii_review_decision(settings, document_id, request)
