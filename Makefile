.PHONY: test test-unit test-cov lint fmt typecheck migrate migration fresh seed db-init install help

# ── Testing ──────────────────────────────────────────────────
test:  ## Run all tests
	python -m pytest tests/ -v

test-unit:  ## Run unit tests only (fast, no containers)
	python -m pytest tests/unit/ -v

test-cov:  ## Run tests with coverage report
	python -m pytest --cov=app --cov=agents --cov=tools --cov-report=term-missing

# ── Code quality ─────────────────────────────────────────────
lint:  ## Run ruff linter + formatter check
	ruff check . && ruff format --check .

fmt:  ## Auto-format code
	ruff check --fix . && ruff format .

typecheck:  ## Run mypy type checking
	mypy app/ agents/ tools/

# ── Database ─────────────────────────────────────────────────
migrate:  ## Run alembic migrations
	alembic upgrade head

migration:  ## Create a new migration (usage: make migration msg="add events table")
	alembic revision --autogenerate -m "$(msg)"

fresh:  ## Reset DB: drop all, recreate, migrate
	alembic downgrade base && alembic upgrade head

seed:  ## Load test data (event + 12 attendees + 30 seats)
	python scripts/seed.py

db-init:  ## Full DB setup: migrate + seed
	alembic upgrade head && python scripts/seed.py

# ── Install ──────────────────────────────────────────────────
install:  ## Install project + dev dependencies
	pip install -e ".[dev]"

# ── Help ─────────────────────────────────────────────────────
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
