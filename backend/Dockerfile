# syntax=docker/dockerfile:1

# --- Build stage: resolve and install dependencies into a virtualenv ---------------------
FROM python:3.12-slim AS builder

ARG INSTALL_OCR=false

# uv is only a build tool here; runtime dependencies are pinned by uv.lock.
RUN pip install --no-cache-dir "uv>=0.5,<1.0"

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install dependencies first (cached layer), then the project itself (baked into the venv).
COPY pyproject.toml uv.lock ./
RUN if [ "$INSTALL_OCR" = "true" ]; then \
        uv sync --frozen --no-install-project --no-dev --extra ocr; \
    else \
        uv sync --frozen --no-install-project --no-dev; \
    fi
COPY README.md ./
COPY app ./app
RUN if [ "$INSTALL_OCR" = "true" ]; then \
        uv sync --frozen --no-dev --no-editable --extra ocr; \
    else \
        uv sync --frozen --no-dev --no-editable; \
    fi

# --- Runtime stage: minimal, non-root -----------------------------------------------------
FROM python:3.12-slim AS runtime

# Poppler provides pdftoppm/pdftocairo for pdf2image. Create an unprivileged user to run the
# service and pre-create the upload directory owned by that user so an initially empty mounted
# volume inherits writable ownership.
RUN apt-get update \
    && apt-get install --no-install-recommends --yes poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --no-create-home app \
    && mkdir -p /data/uploads \
    && chown -R app:app /data

WORKDIR /app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder --chown=app:app /app/.venv /app/.venv

USER app
EXPOSE 8000

# --no-access-log: the app emits its own structured (JSON, correlation-linked) request logs.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
