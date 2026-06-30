"""Upload validation and safe storage.

Validation happens at the trust boundary, independent of the HTTP layer:

- the file extension must be on the configured whitelist;
- the file content must start with a magic-byte signature matching that extension, so a
  renamed executable cannot pass as a PDF;
- the size limit is enforced while streaming, so an oversized upload never has to fit in
  memory.

Files are stored under a generated UUID name to prevent path traversal; the original filename
is kept only as metadata. On success, metadata is persisted via the document service so the
upload can be listed and deleted later.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.config import Settings
from app.errors import ApiError
from app.schemas import UploadAccepted
from app.services.document_service import create_document_record, save_metadata

_CHUNK_SIZE = 1024 * 1024  # 1 MiB
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_LEN = 255
_SIGNATURE_PREFIX_LEN = 8

# Leading magic bytes per allowed extension. DOCX is an Office Open XML ZIP container, so we
# only verify the ZIP signature (a deeper OOXML check would require unzipping the upload).
_MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "docx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
}


class UploadValidationError(ApiError):
    """Raised when an upload fails validation. Carries a safe message and HTTP status."""

    def __init__(self, code: str, detail: str, status_code: int) -> None:
        super().__init__(detail, status_code)
        self.code = code


class _AsyncReadable(Protocol):
    """Minimal interface of Starlette's UploadFile used by this service."""

    filename: str | None
    content_type: str | None

    async def read(self, size: int = -1) -> bytes: ...


def sanitize_filename(filename: str) -> str:
    """Reduce a client-supplied filename to a safe basename for metadata/logging."""
    base = Path(filename).name.strip()
    base = _SAFE_FILENAME.sub("_", base)
    base = base.strip("._") or "upload"
    return base[:_MAX_FILENAME_LEN]


def _extension_of(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def content_matches_extension(extension: str, head: bytes) -> bool:
    """True if the leading bytes match a known signature for the extension."""
    signatures = _MAGIC_SIGNATURES.get(extension)
    if signatures is None:
        return True  # whitelisted but no signature on file; accept by extension alone
    return any(head.startswith(signature) for signature in signatures)


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

    size, head = await _stream_to_disk(file, partial, settings.max_upload_bytes)

    if size == 0:
        partial.unlink(missing_ok=True)
        raise UploadValidationError("empty_file", "The uploaded file is empty.", 400)

    if not content_matches_extension(extension, head):
        partial.unlink(missing_ok=True)
        raise UploadValidationError(
            "content_mismatch",
            "The file content does not match its extension.",
            415,
        )

    partial.replace(destination)

    record = create_document_record(
        document_id=document_id,
        filename=safe_name,
        extension=extension,
        size=size,
        content_type=file.content_type,
    )
    save_metadata(settings, record)

    return UploadAccepted(id=document_id, filename=safe_name, size=size)


async def _stream_to_disk(file: _AsyncReadable, target: Path, max_bytes: int) -> tuple[int, bytes]:
    """Stream the upload to ``target`` in chunks, enforcing ``max_bytes``.

    Returns the total size and the leading bytes (for signature validation).
    """
    size = 0
    head = b""
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                if not head:
                    head = chunk[:_SIGNATURE_PREFIX_LEN]
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
    return size, head
