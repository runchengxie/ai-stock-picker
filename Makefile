.PHONY: check lock lint format type test maintainability build

check: lock lint format type test maintainability build ## Run every release gate

lock: ## Verify dependency lock freshness
	uv lock --check

lint: ## Run Ruff lint checks
	uv run ruff check .

format: ## Verify Ruff formatting
	uv run ruff format --check .

type: ## Run strict static typing
	uv run mypy

test: ## Run the default suite and 75% branch coverage gate
	uv run pytest

maintainability: ## Enforce maintainability ratchet
	uv run python scripts/dev/maintainability_metrics.py --ratchet

build: ## Build wheel and source distribution
	uv run python -m build
