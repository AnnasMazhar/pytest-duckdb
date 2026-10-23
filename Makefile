.PHONY: help test lint security-audit security-deps pre-commit-install pre-commit-run security-all clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

test: ## Run tests
	uv run pytest -v --tb=short

lint: ## Run ruff linter and formatter
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

security-audit: ## Run bandit security scan
	uv run bandit -r src/ -ll

security-deps: ## Check dependencies for vulnerabilities
	uv run pip-audit

pre-commit-install: ## Install pre-commit hooks
	uv run pre-commit install

pre-commit-run: ## Run pre-commit on all files
	uv run pre-commit run --all-files

security-all: security-audit security-deps ## Run all security checks

clean: ## Clean build artifacts
	rm -rf dist/ build/ *.egg-info/ .coverage coverage.xml __pycache__/ .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
