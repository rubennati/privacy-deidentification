"""FastAPI application factory: middleware, logging, routing, and error handling."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app import __version__
from app.api import audits, config, documents, health, jobs, ocr, pii, uploads
from app.config import get_settings
from app.errors import ApiError
from app.logging import configure_logging, set_correlation_id
from app.schemas import ErrorResponse
from app.services.runtime_capabilities import warn_if_ocr_memory_limit_is_low

logger = logging.getLogger("app")

_CORRELATION_HEADER = "X-Request-ID"

# Health probes fire every few seconds; don't log them to keep request logs signal-rich.
_UNLOGGED_PREFIXES = ("/api/health",)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)
    warn_if_ocr_memory_limit_is_low(settings, logger)

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
    app.include_router(config.router, prefix="/api")
    app.include_router(uploads.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(audits.router, prefix="/api")
    app.include_router(ocr.router, prefix="/api")
    app.include_router(pii.router, prefix="/api")
    return app


def _register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_and_logging(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = request.headers.get(_CORRELATION_HEADER) or uuid4().hex
        set_correlation_id(correlation_id)

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)

        response.headers[_CORRELATION_HEADER] = correlation_id
        _log_request(request, response.status_code, duration_ms)
        return response


def _log_request(request: Request, status_code: int, duration_ms: float) -> None:
    """Emit one structured JSON line per request. Skips noisy health probes; logs only the
    path (never the query string), so no PII or filenames leak into logs."""
    if request.url.path.startswith(_UNLOGGED_PREFIXES):
        return
    logger.info(
        "request",
        extra={
            "http_method": request.method,
            "http_path": request.url.path,
            "http_status": status_code,
            "duration_ms": duration_ms,
        },
    )


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        from app.logging import get_correlation_id

        correlation_id = get_correlation_id()
        logger.info("request rejected (%s): %s", exc.status_code, exc.detail)
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
