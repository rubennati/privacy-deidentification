# syntax=docker/dockerfile:1

# --- Build stage: resolve and install dependencies into a virtualenv ---------------------
FROM python:3.12-slim AS builder

# uv is only a build tool here; runtime dependencies are pinned by uv.lock.
RUN pip install --no-cache-dir "uv>=0.5,<1.0"

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install dependencies first (cached layer), then the project itself (baked into the venv).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY README.md ./
COPY app ./app
RUN uv sync --frozen --no-dev --no-editable

# --- Runtime stage: minimal, non-root -----------------------------------------------------
FROM python:3.12-slim AS runtime

# Create an unprivileged user to run the service. Pre-create the upload directory owned by
# that user so the mounted (initially empty) volume inherits writable ownership.
RUN groupadd --system app \
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
