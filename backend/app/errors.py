"""Application-level errors mapped to clean JSON responses by app.main."""

from __future__ import annotations


class ApiError(Exception):
    """Base for errors that surface as a clean JSON response, never a stack trace."""

    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
