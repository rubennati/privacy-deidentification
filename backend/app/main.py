"""FastAPI application factory: middleware, logging, routing, and error handling."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app import __version__
from app.api import health, uploads
from app.config import get_settings
from app.logging import configure_logging, set_correlation_id
from app.schemas import ErrorResponse
from app.services.upload_service import UploadValidationError

logger = logging.getLogger("app")

_CORRELATION_HEADER = "X-Request-ID"

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Privacy De-Identification Pilot API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # Same-origin in production (nginx proxies /api). CORS stays closed by default.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    _register_middleware(app)
    _register_exception_handlers(app)

    app.include_router(health.router, prefix="/api")
    app.include_router(uploads.router, prefix="/api")
    return app


def _register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_and_security(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = request.headers.get(_CORRELATION_HEADER) or uuid4().hex
        set_correlation_id(correlation_id)
        response = await call_next(request)
        response.headers[_CORRELATION_HEADER] = correlation_id
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(UploadValidationError)
    async def handle_upload_validation(
        request: Request, exc: UploadValidationError
    ) -> JSONResponse:
        from app.logging import get_correlation_id

        correlation_id = get_correlation_id()
        logger.info("upload rejected: %s", exc.code)
        body = ErrorResponse(detail=exc.detail, correlation_id=correlation_id)
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        from app.logging import get_correlation_id

        correlation_id = get_correlation_id()
        logger.exception("unhandled error")
        body = ErrorResponse(
            detail="An internal error occurred. Please try again later.",
            correlation_id=correlation_id,
        )
        return JSONResponse(status_code=500, content=body.model_dump())


app = create_app()
