# Quality and lifecycle commands. Everything runs in containers — no host toolchain needed.

.DEFAULT_GOAL := help
COMPOSE := docker compose

# One-off tool runners. Dependency caches live in named volumes so repeated runs are fast
# and the host working tree stays clean.
BACKEND_RUN := docker run --rm -v "$(CURDIR)/backend":/app -v deid-backend-venv:/app/.venv \
	-w /app ghcr.io/astral-sh/uv:python3.12-bookworm-slim sh -lc
FRONTEND_RUN := docker run --rm -v "$(CURDIR)/frontend":/app -v deid-frontend-modules:/app/node_modules \
	-w /app node:22-alpine sh -lc

.PHONY: help up down build rebuild logs ps lint typecheck test lock clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Build and start the stack (http://localhost:8080)
	$(COMPOSE) up -d --build

down: ## Stop the stack
	$(COMPOSE) down

build: ## Build both images
	$(COMPOSE) build

rebuild: ## Rebuild images without cache
	$(COMPOSE) build --no-cache

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
