# Quality and lifecycle commands. Everything runs in containers — no host toolchain needed.

.DEFAULT_GOAL := help
COMPOSE := docker compose
# Single host data root, mirrored from docker-compose.yml's DATA_ROOT default. Override to relocate
# all bind-mounted storage (uploads, document-store, job-state, feedback archive, OCR models).
DATA_ROOT ?= volumes

# One-off tool runners. Dependency caches live in named volumes so repeated runs are fast and the
# host working tree stays clean.
BACKEND_RUN := docker run --rm -v "$(CURDIR)/backend":/app -v privacy-deidentification-backend-venv:/app/.venv \
	-w /app ghcr.io/astral-sh/uv:python3.12-bookworm-slim sh -lc
FRONTEND_RUN := docker run --rm -v "$(CURDIR)/frontend":/app -v privacy-deidentification-frontend-modules:/app/node_modules \
	-w /app node:22-alpine sh -lc
RUNTIME_RUN := docker run --rm -v "$(CURDIR)":/repo -w /repo python:3.12-slim sh -lc
BENCHMARK_RUN := docker run --rm -v "$(CURDIR)":/repo -w /repo python:3.12-slim sh -lc

.PHONY: help runtime-dirs up down build rebuild ocr-models ocr-smoke pii-smoke logs ps shell-api \
	lint typecheck test lock benchmark-private benchmark-private-json benchmark-test docker-df

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

runtime-dirs: ## Create local bind-mount roots used by Compose
	mkdir -p $(DATA_ROOT)/uploads $(DATA_ROOT)/document-store $(DATA_ROOT)/job-state \
		$(DATA_ROOT)/pii-feedback-archive $(DATA_ROOT)/ocr-models

up: runtime-dirs ## Build and start frontend + api + ocr-worker (http://localhost:8080)
	$(COMPOSE) up -d --build

down: ## Stop the stack; uploads, artifacts, models, and SQLite job state remain on disk
	$(COMPOSE) down

build: ## Build the frontend and shared api/ocr-worker image
	$(COMPOSE) build

rebuild: ## Rebuild images without cache
	$(COMPOSE) build --no-cache

ocr-models: ## Download PaddleOCR models into volumes/ocr-models (idempotent)
	./scripts/fetch-ocr-models.sh

ocr-smoke: ## Smoke-test the real OCR runtime (needs provisioned models)
	$(COMPOSE) build api
	$(COMPOSE) run --rm --no-deps -v "$(CURDIR)/scripts":/opt/scripts:ro \
		api python /opt/scripts/ocr_smoke.py

pii-smoke: ## Smoke-test the real PII runtime
	$(COMPOSE) build api
	$(COMPOSE) run --rm --no-deps -v "$(CURDIR)/scripts":/opt/scripts:ro \
		api python /opt/scripts/pii_smoke.py

logs: ## Tail service logs
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

shell-api: runtime-dirs ## Open a shell in the API image
	$(COMPOSE) run --rm --no-deps api sh

lint: ## Ruff (backend) + ESLint (frontend)
	$(BACKEND_RUN) "uv sync --frozen --quiet && uv run ruff check ."
	$(FRONTEND_RUN) "npm ci --no-audit --no-fund --silent && npm run lint"

typecheck: ## mypy (backend) + tsc (frontend)
	$(BACKEND_RUN) "uv sync --frozen --quiet && uv run mypy app"
	$(FRONTEND_RUN) "npm ci --no-audit --no-fund --silent && npm run typecheck"

test: ## Runtime surface checks + pytest (backend) + Vitest (frontend)
	$(RUNTIME_RUN) "python scripts/check-runtime-surface.py"
	$(BACKEND_RUN) "uv sync --frozen --quiet && uv run pytest"
	$(FRONTEND_RUN) "npm ci --no-audit --no-fund --silent && npm test"

lock: ## (Re)generate dependency lockfiles (backend uv.lock + frontend package-lock.json)
	$(BACKEND_RUN) "uv lock"
	$(FRONTEND_RUN) "npm install --package-lock-only --no-audit --no-fund"

benchmark-private: ## Private local OCR/PII benchmark report (reads existing artifacts only)
	$(BENCHMARK_RUN) "python scripts/benchmark/private_benchmark.py \
		--uploads-dir $(DATA_ROOT)/uploads \
		--document-data-dir $(DATA_ROOT)/document-store \
		--metadata $(DATA_ROOT)/benchmark/ocr_pii_benchmark_metadata.json \
		--groundtruth $(DATA_ROOT)/benchmark/ocr_pii_benchmark_pii_groundtruth.json \
		--output-dir $(DATA_ROOT)/benchmark/reports"

benchmark-private-json: ## Same as benchmark-private, JSON report only
	$(BENCHMARK_RUN) "python scripts/benchmark/private_benchmark.py \
		--uploads-dir $(DATA_ROOT)/uploads \
		--document-data-dir $(DATA_ROOT)/document-store \
		--metadata $(DATA_ROOT)/benchmark/ocr_pii_benchmark_metadata.json \
		--groundtruth $(DATA_ROOT)/benchmark/ocr_pii_benchmark_pii_groundtruth.json \
		--output-dir $(DATA_ROOT)/benchmark/reports \
		--json-only"

benchmark-test: ## Run the private benchmark runner's synthetic unit tests (no OCR/PII deps)
	$(BENCHMARK_RUN) "pip install --quiet pytest && python -m pytest scripts/benchmark/tests -q"

docker-df: ## Show Docker disk usage (images, containers, volumes, build cache)
	docker system df
	docker system df -v
