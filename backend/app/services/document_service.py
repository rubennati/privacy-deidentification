"""Document metadata persistence and lookup.

Metadata is stored as a JSON sidecar file (``{id}.meta.json``) next to each uploaded file in
the upload directory — no database. Document ids are generated server-side (``uuid4().hex``)
and are validated against that exact shape before they are ever used to build a filesystem
path, which rules out path traversal by construction rather than by sanitizing.
"""

from __future__ import annotations

import os
import re
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.config import Settings
from app.errors import ApiError
from app.schemas import DocumentSummary, OriginalArtifact

_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_EXTENSION_PATTERN = r"^[a-z0-9]{1,10}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_METADATA_SUFFIX = ".meta.json"


class DocumentNotFoundError(ApiError):
    """Raised when a document id does not resolve to a stored document."""

    def __init__(self) -> None:
        super().__init__("Document not found.", 404)


class DocumentRecord(BaseModel):
    """Metadata persisted as a JSON sidecar next to each stored upload (internal format)."""

    id: str = Field(pattern=_ID_PATTERN.pattern)
    filename: str
    extension: str = Field(pattern=_EXTENSION_PATTERN)
    size: int = Field(ge=0)
    content_type: str | None = None
    uploaded_at: str
    status: str = "received"
    # Optional defaults preserve readability of sidecars created before Upload/Core metadata
    # was introduced. Every newly created record populates all three fields.
    sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    detected_mime_type: str | None = None
    original_artifact: OriginalArtifact | None = None

    @model_validator(mode="after")
    def _validate_original_artifact(self) -> DocumentRecord:
        artifact = self.original_artifact
        if artifact is None:
            return self
        if artifact.document_id != self.id:
            raise ValueError("original artifact belongs to a different document")
        if artifact.storage_filename != f"{self.id}.{self.extension}":
            raise ValueError("original artifact storage filename does not match the document")
        if artifact.sha256 != self.sha256:
            raise ValueError("original artifact hash does not match the document")
        if artifact.mime_type != self.detected_mime_type:
            raise ValueError("original artifact MIME type does not match the document")
        if artifact.size_bytes != self.size:
            raise ValueError("original artifact size does not match the document")
        return self


def is_valid_document_id(document_id: str) -> bool:
    """Server-generated ids are 32-char lowercase hex (``uuid4().hex``); reject anything else."""
    return bool(_ID_PATTERN.fullmatch(document_id))


def now_utc_iso() -> str:
    """Current time as a UTC ISO 8601 timestamp, e.g. ``2026-06-30T18:00:00Z``."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def create_document_record(
    *,
    document_id: str,
    filename: str,
    extension: str,
    size: int,
    sha256: str,
    detected_mime_type: str,
    storage_filename: str,
) -> DocumentRecord:
    """Build the metadata record for a freshly stored upload."""
    created_at = now_utc_iso()
    original_artifact = OriginalArtifact(
        id=uuid4().hex,
        document_id=document_id,
        storage_filename=storage_filename,
        sha256=sha256,
        mime_type=detected_mime_type,
        size_bytes=size,
        created_at=created_at,
    )
    return DocumentRecord(
        id=document_id,
        filename=filename,
        extension=extension,
        size=size,
        # Keep the existing field for API compatibility, but never populate it from the
        # untrusted multipart Content-Type header.
        content_type=detected_mime_type,
        uploaded_at=created_at,
        status="received",
        sha256=sha256,
        detected_mime_type=detected_mime_type,
        original_artifact=original_artifact,
    )


def save_metadata(settings: Settings, record: DocumentRecord) -> None:
    """Persist metadata through a temporary sidecar and an atomic same-filesystem rename."""
    destination = _metadata_path(settings, record.id)
    partial = destination.with_name(destination.name + ".part")
    try:
        with partial.open("w", encoding="utf-8") as metadata_file:
            metadata_file.write(record.model_dump_json())
            metadata_file.flush()
            os.fsync(metadata_file.fileno())
        partial.replace(destination)
    except Exception:
        with suppress(OSError):
            partial.unlink(missing_ok=True)
        raise


def delete_metadata(settings: Settings, document_id: str) -> None:
    """Remove final and temporary metadata for rollback or document deletion."""
    destination = _metadata_path(settings, document_id)
    destination.unlink(missing_ok=True)
    destination.with_name(destination.name + ".part").unlink(missing_ok=True)


def list_documents(settings: Settings) -> list[DocumentSummary]:
    """Return all stored documents, newest first. Unreadable sidecars are skipped."""
    records = [
        record
        for meta_file in settings.upload_dir.glob(f"*{_METADATA_SUFFIX}")
        if (record := _read_record(meta_file)) is not None
    ]
    records.sort(key=lambda record: record.uploaded_at, reverse=True)
    return [_to_summary(record) for record in records]


def get_document_record(settings: Settings, document_id: str) -> DocumentRecord | None:
    """Look up one document's metadata by id. Returns None for invalid or unknown ids."""
    if not is_valid_document_id(document_id):
        return None
    return _read_record(_metadata_path(settings, document_id))


def delete_document(settings: Settings, document_id: str) -> None:
    """Delete a document's stored file and metadata.

    Raises DocumentNotFoundError for unknown or unsafe ids — the id is validated before it is
    ever used to build a filesystem path, so this also rejects path-traversal-style ids.
    """
    record = get_document_record(settings, document_id)
    if record is None:
        raise DocumentNotFoundError

    storage_filename = (
        record.original_artifact.storage_filename
        if record.original_artifact is not None
        else f"{document_id}.{record.extension}"
    )
    stored_file = settings.upload_dir / storage_filename
    stored_file.unlink(missing_ok=True)
    delete_metadata(settings, document_id)


def _metadata_path(settings: Settings, document_id: str) -> Path:
    return settings.upload_dir / f"{document_id}{_METADATA_SUFFIX}"


def _read_record(path: Path) -> DocumentRecord | None:
    try:
        return DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None


def _to_summary(record: DocumentRecord) -> DocumentSummary:
    return DocumentSummary(
        id=record.id,
        filename=record.filename,
        size=record.size,
        content_type=record.content_type,
        uploaded_at=record.uploaded_at,
        status=record.status,
        sha256=record.sha256,
        detected_mime_type=record.detected_mime_type,
        original_artifact=record.original_artifact,
    )
