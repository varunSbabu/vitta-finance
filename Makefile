# Vitta — dev conveniences. Every target here maps to the raw command
# it wraps, printed below in the recipe, so nothing hides behind Make.
# Run `make help` to list what's available.

.PHONY: help dev up down logs test lint format precommit ci

help: ## Show this help
	@awk 'BEGIN{FS=":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} \
	     /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

dev: ## Build images + start api + web in the background
	docker compose up -d --build api web
	@echo ""
	@echo "  api: http://localhost:8001/api/health"
	@echo "  web: http://localhost:5757/"

up: ## Start api + web without rebuilding
	docker compose up -d api web

down: ## Stop everything, keep volumes
	docker compose down

logs: ## Tail api + web logs
	docker compose logs -f api web

test: ## Run pytest (needs the local .venv, not Docker)
	cd vitta/backend && ../.venv/bin/python -m pytest

lint: ## Ruff check (backend)
	cd vitta/backend && ../.venv/bin/ruff check .

format: ## Ruff format in-place (backend)
	cd vitta/backend && ../.venv/bin/ruff format .

precommit: ## Run every pre-commit hook against all files
	vitta/.venv/bin/pre-commit run --all-files

ci: lint test ## What CI runs — lint + tests
