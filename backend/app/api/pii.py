"""Synchronous PII Workstation v1 endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, Response, status

from app.config import Settings, get_settings
from app.schemas import (
    ErrorResponse,
    PiiArtifact,
    PiiEntityContractV1,
    PiiFeedbackAck,
    PiiFeedbackRequest,
    PiiFeedbackSummary,
    PiiReviewDecisionAck,
    PiiReviewDecisionRequest,
    PiiReviewResult,
    PiiReviewResultArtifact,
    PiiRunRequest,
)
from app.services.feedback_service import record_pii_feedback, summarize_pii_feedback
from app.services.job_models import JobContext, JobKind
from app.services.job_runner import SyncJobRunner, provide_job_runner
from app.services.pii_adapters import PiiAnalyzer, get_pii_analyzer
from app.services.pii_entity_contract import build_pii_entity_contract
from app.services.pii_review_service import (
    get_pii_review_result,
    get_pii_review_result_artifact,
    set_pii_review_decision,
)
from app.services.pii_service import create_pii_artifact, get_latest_pii

router = APIRouter(prefix="/documents", tags=["pii"])
_JOB_ID_HEADER = "X-Job-Id"


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
    response: Response,
    request: PiiRunRequest | None = Body(default=None),
    settings: Settings = Depends(get_settings),
    analyzer: PiiAnalyzer = Depends(provide_pii_analyzer),
    runner: SyncJobRunner = Depends(provide_job_runner),
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
    response.headers[_JOB_ID_HEADER] = result.record.job_id
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


@router.get(
    "/{document_id}/pii/review-result",
    response_model=PiiReviewResultArtifact,
    responses={404: {"model": ErrorResponse}},
)
def get_document_pii_review_result_artifact(
    document_id: str, settings: Settings = Depends(get_settings)
) -> PiiReviewResultArtifact:
    """Return the newest persisted review-result snapshot artifact (Review L8, ADR-0034).

    Additive alongside ``GET …/pii/review``: that endpoint recomputes the reviewable view fresh on
    every call, while this one returns the durable, immutable-per-run artifact written after each
    recorded decision — the same file-based artifact model as ``original``/``audit``/``text``/
    ``pii``. Raises a clean 404 when no decision has ever been recorded for this document yet
    (distinct from "no PII result exists").
    """
    return get_pii_review_result_artifact(settings, document_id)


@router.get(
    "/{document_id}/pii/entity-contract",
    response_model=PiiEntityContractV1,
    responses={404: {"model": ErrorResponse}},
)
def get_document_pii_entity_contract(
    document_id: str, settings: Settings = Depends(get_settings)
) -> PiiEntityContractV1:
    """Return the review-ready PII entity contract for the document's latest PII result (ADR-0029).

    Additive alongside ``GET …/pii`` and ``GET …/pii/review``: a derived, review-facing view that
    connects each detected entity to the technical raw text and canonical reading text with an
    explicit mapping status, a stable entity id, deterministic overlap provenance, the resolved
    review state, and a text-free display model. It never mutates the immutable ``pii_result`` and
    raises the same clean 404 as ``GET …/pii/review`` when no PII result exists yet.
    """
    return build_pii_entity_contract(settings, document_id)


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
