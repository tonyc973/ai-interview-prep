SHELL := /bin/bash
.DEFAULT_GOAL := help

# Load .env (if present) for targets that need it (dev, migrate, upgrade, smoke).
define load_env
set -a; [ -f .env ] && . ./.env; set +a;
endef

.PHONY: help install dev lint format typecheck test coverage migrate upgrade smoke docker check clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install locked dependencies (uv sync)
	uv sync

dev: ## Run the app locally (loads .env)
	@$(load_env) uv run python -m app.main

lint: ## ruff check + format check
	uv run ruff check .
	uv run ruff format --check .

format: ## Auto-fix lint + format
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## mypy --strict
	uv run mypy app/ tests/

test: ## Run all tests (LLM gateway always mocked)
	uv run pytest

coverage: ## Run tests with coverage; fail under 85% on services/agents/db
	uv run pytest --cov=app/services --cov=app/agents --cov=app/db \
		--cov-report=term-missing --cov-fail-under=85

migrate: ## Autogenerate a migration: make migrate m="message"
	@$(load_env) uv run alembic revision --autogenerate -m "$(m)"

upgrade: ## Apply migrations to head
	@$(load_env) uv run alembic upgrade head

smoke: ## ONE real OpenAI smoke run (opt-in; never in CI)
	@$(load_env) uv run python -m scripts.smoke

docker: ## Build the production Docker image
	DOCKER_BUILDKIT=1 docker build -t ai-interview-prep:latest .

check: lint typecheck test ## The full local gate (lint + typecheck + test)

clean: ## Remove caches and local artifacts
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
