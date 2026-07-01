"""Synchronous OCR/Text Workstation v1 endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.config import Settings, get_settings
from app.schemas import ErrorResponse, TextArtifact
from app.services.ocr_adapters import OcrAdapter, get_ocr_adapter
from app.services.ocr_service import create_text_artifact, get_latest_text
from app.services.pdf_renderer import PdfRenderer, get_pdf_renderer

router = APIRouter(prefix="/documents", tags=["ocr"])


def provide_ocr_adapter(settings: Settings = Depends(get_settings)) -> OcrAdapter:
    """Bind the runtime's explicitly configured local model directory and names to the adapter."""
    model_dir = str(settings.ocr_model_dir) if settings.ocr_model_dir is not None else None
    return get_ocr_adapter(
        model_dir,
        settings.ocr_detection_model_name,
        settings.ocr_recognition_model_name,
    )


@router.post(
    "/{document_id}/ocr",
    response_model=TextArtifact,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def ocr_document(
    document_id: str,
    settings: Settings = Depends(get_settings),
    ocr_adapter: OcrAdapter = Depends(provide_ocr_adapter),
    pdf_renderer: PdfRenderer = Depends(get_pdf_renderer),
) -> TextArtifact:
    """Extract text according to the latest audit and persist an immutable result."""
    return create_text_artifact(settings, document_id, ocr_adapter, pdf_renderer)


@router.get(
    "/{document_id}/ocr",
    response_model=TextArtifact,
    responses={404: {"model": ErrorResponse}},
)
def get_document_ocr(
    document_id: str, settings: Settings = Depends(get_settings)
) -> TextArtifact:
    """Return the newest text result for a document."""
    return get_latest_text(settings, document_id)
