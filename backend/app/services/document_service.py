"""Document metadata persistence and lookup.

Metadata is stored as a JSON sidecar file (``{id}.meta.json``) next to each uploaded file in
the upload directory — no database. Document ids are generated server-side (``uuid4().hex``)
and are validated against that exact shape before they are ever used to build a filesystem
path, which rules out path traversal by construction rather than by sanitizing.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.errors import ApiError
from app.schemas import DocumentSummary

_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_EXTENSION_PATTERN = r"^[a-z0-9]{1,10}$"
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
    content_type: str | None,
) -> DocumentRecord:
    """Build the metadata record for a freshly stored upload."""
    return DocumentRecord(
        id=document_id,
        filename=filename,
        extension=extension,
        size=size,
        content_type=content_type,
        uploaded_at=now_utc_iso(),
        status="received",
    )


def save_metadata(settings: Settings, record: DocumentRecord) -> None:
    """Persist a document's metadata as a JSON sidecar file."""
    _metadata_path(settings, record.id).write_text(record.model_dump_json(), encoding="utf-8")


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

    stored_file = settings.upload_dir / f"{document_id}.{record.extension}"
    stored_file.unlink(missing_ok=True)
    _metadata_path(settings, document_id).unlink(missing_ok=True)


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
    )
