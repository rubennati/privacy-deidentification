"""Document metadata persistence and lookup.

Each document has an isolated directory under the document-data root. Its metadata is stored
as ``document.json`` and derived results live below ``artifacts/``. Original bytes remain in
the separate upload-storage root. Document ids are generated server-side (``uuid4().hex``)
and validated before they are ever used to build a filesystem path.
"""

from __future__ import annotations

import os
import re
import shutil
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
_METADATA_FILENAME = "document.json"
_ARTIFACTS_DIRECTORY = "artifacts"


class DocumentNotFoundError(ApiError):
    """Raised when a document id does not resolve to a stored document."""

    def __init__(self) -> None:
        super().__init__("Document not found.", 404)


class DocumentRecord(BaseModel):
    """Metadata persisted in one document-data directory (internal format)."""

    id: str = Field(pattern=_ID_PATTERN.pattern)
    filename: str
    extension: str = Field(pattern=_EXTENSION_PATTERN)
    size: int = Field(ge=0)
    content_type: str | None = None
    uploaded_at: str
    status: str = "received"
    # Optional defaults preserve readability of records created before Upload/Core metadata
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
    """Create a document-data directory and atomically persist its metadata."""
    document_directory = _document_directory(settings, record.id)
    document_directory.mkdir(parents=True, exist_ok=True)
    (document_directory / _ARTIFACTS_DIRECTORY).mkdir(exist_ok=True)
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


def delete_document_data(settings: Settings, document_id: str) -> None:
    """Remove exactly one validated document-data directory, if it exists."""
    directory = _document_directory(settings, document_id)
    if directory.is_symlink():
        directory.unlink()
    elif directory.exists():
        shutil.rmtree(directory)


def list_documents(settings: Settings) -> list[DocumentSummary]:
    """Return all stored documents, newest first. Unreadable records are skipped."""
    records = [
        record
        for meta_file in settings.document_data_dir.glob(f"*/{_METADATA_FILENAME}")
        if (record := _read_record(meta_file, expected_id=meta_file.parent.name)) is not None
    ]
    records.sort(key=lambda record: record.uploaded_at, reverse=True)
    return [_to_summary(record) for record in records]


def get_document_record(settings: Settings, document_id: str) -> DocumentRecord | None:
    """Look up one document's metadata by id. Returns None for invalid or unknown ids."""
    if not is_valid_document_id(document_id):
        return None
    return _read_record(_metadata_path(settings, document_id), expected_id=document_id)


def get_document(settings: Settings, document_id: str) -> DocumentSummary:
    """Return one public document representation or raise the existing safe 404."""
    record = get_document_record(settings, document_id)
    if record is None:
        raise DocumentNotFoundError
    return _to_summary(record)


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
    stored_file = settings.upload_storage_dir / storage_filename
    stored_file.unlink(missing_ok=True)
    delete_document_data(settings, document_id)


def _document_directory(settings: Settings, document_id: str) -> Path:
    if not is_valid_document_id(document_id):
        raise ValueError("invalid document id")
    return settings.document_data_dir / document_id


def _metadata_path(settings: Settings, document_id: str) -> Path:
    return _document_directory(settings, document_id) / _METADATA_FILENAME


def _read_record(path: Path, expected_id: str | None = None) -> DocumentRecord | None:
    try:
        record = DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None
    if expected_id is not None and record.id != expected_id:
        return None
    return record


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
