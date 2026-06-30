"""Upload endpoint. Accepts one document and hands it to the upload service."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.config import Settings, get_settings
from app.schemas import ErrorResponse, UploadAccepted
from app.services.upload_service import UploadValidationError, store_upload

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post(
    "",
    response_model=UploadAccepted,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
    },
)
async def create_upload(
    file: UploadFile | None = File(default=None),
    settings: Settings = Depends(get_settings),
) -> UploadAccepted:
    """Validate and store an uploaded document.

    Validation failures are raised as ``UploadValidationError`` and mapped to clean error
    responses by the exception handler in ``app.main``.
    """
    if file is None:
        raise UploadValidationError("missing_file", "No file was provided.", 400)
    return await store_upload(file, settings)
