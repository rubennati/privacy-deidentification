# Quality and lifecycle commands. Everything runs in containers — no host toolchain needed.

.DEFAULT_GOAL := help
COMPOSE := docker compose

# One-off tool runners. Dependency caches live in named volumes so repeated runs are fast
# and the host working tree stays clean.
BACKEND_RUN := docker run --rm -v "$(CURDIR)/backend":/app -v deid-backend-venv:/app/.venv \
	-w /app ghcr.io/astral-sh/uv:python3.12-bookworm-slim sh -lc
FRONTEND_RUN := docker run --rm -v "$(CURDIR)/frontend":/app -v deid-frontend-modules:/app/node_modules \
	-w /app node:22-alpine sh -lc
# The private benchmark runner is stdlib-only (no app dependencies), so it gets its own minimal
# Python image rather than the backend's uv-managed venv.
BENCHMARK_RUN := docker run --rm -v "$(CURDIR)":/repo -w /repo python:3.12-slim sh -lc

# Runtime profiles select the optional heavy extras via build args. The profile is chosen by the
# target, not by .env, so `make up` is always slim regardless of local .env values. OCR/PII images
# get more memory headroom for PaddlePaddle/spaCy.
SLIM  := INSTALL_OCR=false INSTALL_PII=false
PII   := INSTALL_OCR=false INSTALL_PII=true  BACKEND_MEMORY_LIMIT=1g
OCR   := INSTALL_OCR=true  INSTALL_PII=false BACKEND_MEMORY_LIMIT=2g
FULL  := INSTALL_OCR=true  INSTALL_PII=true  BACKEND_MEMORY_LIMIT=2g

.PHONY: help up up-pii up-ocr up-full down build build-pii build-ocr build-full rebuild \
	ocr-models ocr-smoke pii-smoke logs ps lint typecheck test lock clean \
	benchmark-private benchmark-private-json benchmark-test

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

up: ## Build and start the slim stack — no OCR/PII runtime (http://localhost:8080)
	$(SLIM) $(COMPOSE) up -d --build

up-pii: ## Start with the PII runtime (Presidio/spaCy)
	$(PII) $(COMPOSE) up -d --build

up-ocr: ## Start with the OCR runtime (needs `make ocr-models` first)
	$(OCR) $(COMPOSE) up -d --build

up-full: ## Start with both OCR and PII runtimes (needs `make ocr-models` first)
	$(FULL) $(COMPOSE) up -d --build

down: ## Stop the stack
	$(COMPOSE) down

build: ## Build both images (slim)
	$(SLIM) $(COMPOSE) build

build-pii: ## Build the backend with the PII runtime
	$(PII) $(COMPOSE) build

build-ocr: ## Build the backend with the OCR runtime
	$(OCR) $(COMPOSE) build

build-full: ## Build the backend with both OCR and PII runtimes
	$(FULL) $(COMPOSE) build

rebuild: ## Rebuild slim images without cache
	$(SLIM) $(COMPOSE) build --no-cache

ocr-models: ## Download PaddleOCR models into volumes/ocr-models (idempotent)
	./scripts/fetch-ocr-models.sh

ocr-smoke: ## Smoke-test the real OCR runtime (builds OCR image; needs provisioned models)
	$(OCR) $(COMPOSE) build backend
	$(OCR) $(COMPOSE) run --rm --no-deps -v "$(CURDIR)/scripts":/opt/scripts:ro \
		backend python /opt/scripts/ocr_smoke.py

pii-smoke: ## Smoke-test the real PII runtime (builds PII image)
	$(PII) $(COMPOSE) build backend
	$(PII) $(COMPOSE) run --rm --no-deps -v "$(CURDIR)/scripts":/opt/scripts:ro \
		backend python /opt/scripts/pii_smoke.py

logs: ## Tail service logs
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

lint: ## Ruff (backend) + ESLint (frontend)
	$(BACKEND_RUN) "uv sync --frozen --quiet && uv run ruff check ."
	$(FRONTEND_RUN) "npm ci --no-audit --no-fund --silent && npm run lint"

typecheck: ## mypy (backend) + tsc (frontend)
	$(BACKEND_RUN) "uv sync --frozen --quiet && uv run mypy app"
	$(FRONTEND_RUN) "npm ci --no-audit --no-fund --silent && npm run typecheck"

test: ## pytest (backend) + Vitest (frontend)
	$(BACKEND_RUN) "uv sync --frozen --quiet && uv run pytest"
	$(FRONTEND_RUN) "npm ci --no-audit --no-fund --silent && npm test"

lock: ## (Re)generate dependency lockfiles (backend uv.lock + frontend package-lock.json)
	$(BACKEND_RUN) "uv lock"
	$(FRONTEND_RUN) "npm install --package-lock-only --no-audit --no-fund"

clean: ## Remove tooling cache volumes
	-docker volume rm deid-backend-venv deid-frontend-modules

benchmark-private: ## Private local OCR/PII benchmark report (reads existing artifacts only; never triggers OCR/PII)
	$(BENCHMARK_RUN) "python scripts/benchmark/private_benchmark.py \
		--uploads-dir volumes/uploads \
		--document-data-dir volumes/document-data \
		--metadata volumes/benchmark/ocr_pii_benchmark_metadata.json \
		--groundtruth volumes/benchmark/ocr_pii_benchmark_pii_groundtruth.json \
		--output-dir volumes/benchmark/reports"

benchmark-private-json: ## Same as benchmark-private, JSON report only
	$(BENCHMARK_RUN) "python scripts/benchmark/private_benchmark.py \
		--uploads-dir volumes/uploads \
		--document-data-dir volumes/document-data \
		--metadata volumes/benchmark/ocr_pii_benchmark_metadata.json \
		--groundtruth volumes/benchmark/ocr_pii_benchmark_pii_groundtruth.json \
		--output-dir volumes/benchmark/reports \
		--json-only"

benchmark-test: ## Run the private benchmark runner's synthetic unit tests (no OCR/PII deps)
	$(BENCHMARK_RUN) "pip install --quiet pytest && python -m pytest scripts/benchmark/tests -q"

bf: ## Build and force recreate
	-docker compose up -d --build --force-recreate