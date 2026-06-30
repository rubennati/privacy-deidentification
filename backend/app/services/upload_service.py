"""Upload validation and safe storage.

Validation happens at the trust boundary: allowed extension (whitelist) and size limit are
enforced here, independent of the HTTP layer. Files are streamed to disk in bounded chunks so
an oversized upload never has to fit in memory, and are stored under a generated UUID name to
prevent path traversal. The original filename is kept only as returned metadata.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.config import Settings
from app.schemas import UploadAccepted

_CHUNK_SIZE = 1024 * 1024  # 1 MiB
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_LEN = 255


class UploadValidationError(Exception):
    """Raised when an upload fails validation. Carries a safe message and HTTP status."""

    def __init__(self, code: str, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class _AsyncReadable(Protocol):
    """Minimal interface of Starlette's UploadFile used by this service."""

    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...


def sanitize_filename(filename: str) -> str:
    """Reduce a client-supplied filename to a safe basename for metadata/logging."""
    base = Path(filename).name.strip()
    base = _SAFE_FILENAME.sub("_", base)
    base = base.strip("._") or "upload"
    return base[:_MAX_FILENAME_LEN]


def _extension_of(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix


async def store_upload(file: _AsyncReadable, settings: Settings) -> UploadAccepted:
    """Validate and store one uploaded file. Raises UploadValidationError on rejection."""
    raw_name = (file.filename or "").strip()
    if not raw_name:
        raise UploadValidationError("missing_filename", "A filename is required.", 400)

    safe_name = sanitize_filename(raw_name)
    extension = _extension_of(raw_name)
    if extension not in settings.allowed_extensions:
        allowed = ", ".join(sorted(settings.allowed_extensions))
        raise UploadValidationError(
            "unsupported_type",
            f"Unsupported file type. Allowed types: {allowed}.",
            415,
        )

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    document_id = uuid4().hex
    destination = settings.upload_dir / f"{document_id}.{extension}"
    partial = destination.with_name(destination.name + ".part")

    size = await _stream_to_disk(file, partial, settings.max_upload_bytes)

    if size == 0:
        partial.unlink(missing_ok=True)
        raise UploadValidationError("empty_file", "The uploaded file is empty.", 400)

    partial.replace(destination)
    return UploadAccepted(id=document_id, filename=safe_name, size=size)


async def _stream_to_disk(file: _AsyncReadable, target: Path, max_bytes: int) -> int:
    """Stream the upload to ``target`` in chunks, enforcing ``max_bytes``. Returns size."""
    size = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise UploadValidationError(
                        "too_large",
                        f"File exceeds the maximum size of {max_bytes} bytes.",
                        413,
                    )
                out.write(chunk)
    except UploadValidationError:
        target.unlink(missing_ok=True)
        raise
    return size
