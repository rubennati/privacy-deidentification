"""Document listing and deletion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.config import Settings, get_settings
from app.schemas import DocumentSummary, ErrorResponse
from app.services.document_service import delete_document, get_document, list_documents

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentSummary])
def get_documents(settings: Settings = Depends(get_settings)) -> list[DocumentSummary]:
    """List uploaded documents, newest first."""
    return list_documents(settings)


@router.get(
    "/{document_id}",
    response_model=DocumentSummary,
    responses={404: {"model": ErrorResponse}},
)
def get_document_by_id(
    document_id: str, settings: Settings = Depends(get_settings)
) -> DocumentSummary:
    """Return one uploaded document by its validated server-generated id."""
    return get_document(settings, document_id)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
)
def remove_document(document_id: str, settings: Settings = Depends(get_settings)) -> Response:
    """Delete a document's stored file and metadata.

    Unknown or unsafe ids raise ``DocumentNotFoundError`` (mapped to a clean 404 by
    ``app.main``); the id format is validated before it is ever used in a filesystem path.
    """
    delete_document(settings, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
