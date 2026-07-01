"""Integrity verification shared by stations consuming the uploaded original."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import Settings
from app.errors import ApiError
from app.schemas import OriginalArtifact
from app.services.document_service import DocumentNotFoundError, get_document_record

_HASH_CHUNK_SIZE = 1024 * 1024


class OriginalArtifactConflictError(ApiError):
    """Raised when a document has no usable, byte-identical original artifact."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, 409)


def get_verified_original(
    settings: Settings, document_id: str
) -> tuple[OriginalArtifact, Path]:
    """Resolve an original artifact and verify its persisted SHA-256 digest."""
    record = get_document_record(settings, document_id)
    if record is None:
        raise DocumentNotFoundError
    original = record.original_artifact
    if original is None:
        raise OriginalArtifactConflictError("Document has no verified original artifact.")

    original_path = settings.upload_dir / original.storage_filename
    if not original_path.is_file():
        raise OriginalArtifactConflictError("Original artifact file is unavailable.")
    if sha256_file(original_path) != original.sha256:
        raise OriginalArtifactConflictError("Original artifact integrity check failed.")
    return original, original_path


def sha256_file(path: Path) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as original_file:
        while chunk := original_file.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
