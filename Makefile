# Local defaults match docker-compose.yml (dev-only passwords). Override via environment.
export DATABASE_URL ?= postgresql+psycopg://alibi_app:local_dev_only@localhost:5432/alibi
export MIGRATION_DATABASE_URL ?= postgresql+psycopg://alibi_owner:local_dev_only@localhost:5432/alibi
export TEST_DATABASE_URL ?= postgresql+psycopg://alibi_app:local_dev_only@localhost:5432/alibi_test
export TEST_MIGRATION_DATABASE_URL ?= postgresql+psycopg://alibi_owner:local_dev_only@localhost:5432/alibi_test
export EVAL_DATABASE_URL ?= postgresql+psycopg://alibi_app:local_dev_only@localhost:5432/alibi_eval
export EVAL_MIGRATION_DATABASE_URL ?= postgresql+psycopg://alibi_owner:local_dev_only@localhost:5432/alibi_eval
export ATTACHMENT_KEY_SECRET ?= local-dev-attachment-secret
export LLM_ENABLED ?= false

.PHONY: install db-up db-down migrate lint fmt test dev run sheet eval ui ui-build

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
	cd backend && uv run ruff check ../eval && uv run ruff format --check ../eval
	cd eval && MYPYPATH=../backend uv run --project ../backend mypy \
		--config-file ../backend/pyproject.toml --explicit-package-bases *.py tests

fmt:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd backend && uv run ruff check --fix ../eval && uv run ruff format ../eval

test:
	cd backend && uv run pytest
	cd backend && uv run pytest ../eval/tests

dev:
	cd backend && uv run uvicorn app.main:app --reload

# Decide every sample line for one org: make run ORG=org_demo_alpha [AS_OF=2026-09-25]
ORG ?= org_demo_alpha
run:
	cd backend && uv run alibi run --report ../data/fee_report_sample.csv \
		--upstream ../data/upstream/ --org $(ORG) $(if $(AS_OF),--as-of $(AS_OF),)

# Held-out eval (eval/README.md). `sheet` rebuilds the labelling sheet from eval/data.
sheet:
	cd backend && uv run python ../eval/make_sheet.py

# Refuses unless both label files are committed; see eval/README.md. Resets alibi_eval.
eval:
	cd backend && uv run python ../eval/run_eval.py

# Review UI (frontend/README.md). Needs the API on :8000 (make dev).
ui:
	cd frontend && npm install && ALIBI_BACKEND_URL=$${ALIBI_BACKEND_URL:-http://localhost:8000} npm run dev

ui-build:
	cd frontend && npm ci && npx eslint && npx next build
