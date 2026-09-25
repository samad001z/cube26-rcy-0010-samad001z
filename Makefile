# Local defaults match docker-compose.yml (dev-only passwords). Override via environment.
export DATABASE_URL ?= postgresql+psycopg://alibi_app:local_dev_only@localhost:5432/alibi
export MIGRATION_DATABASE_URL ?= postgresql+psycopg://alibi_owner:local_dev_only@localhost:5432/alibi
export TEST_DATABASE_URL ?= postgresql+psycopg://alibi_app:local_dev_only@localhost:5432/alibi_test
export TEST_MIGRATION_DATABASE_URL ?= postgresql+psycopg://alibi_owner:local_dev_only@localhost:5432/alibi_test
export ATTACHMENT_KEY_SECRET ?= local-dev-attachment-secret
export LLM_ENABLED ?= false

.PHONY: install db-up db-down migrate lint fmt test dev run

install:
	cd backend && uv sync

db-up:
	docker compose up -d --wait db

db-down:
	docker compose down

migrate:
	cd backend && uv run alembic upgrade head

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests

fmt:
	cd backend && uv run ruff check --fix . && uv run ruff format .

test:
	cd backend && uv run pytest

dev:
	cd backend && uv run uvicorn app.main:app --reload

# Decide every sample line for one org: make run ORG=org_demo_alpha [AS_OF=2026-09-25]
ORG ?= org_demo_alpha
run:
	cd backend && uv run alibi run --report ../data/fee_report_sample.csv \
		--upstream ../data/upstream/ --org $(ORG) $(if $(AS_OF),--as-of $(AS_OF),)
