# Alibi API image for Cloud Run. Build from the repository root (the app reads ../config):
#   docker build -f backend/Dockerfile -t alibi-api .
# No credential is ever copied in: settings come from Cloud Run env vars and Secret Manager,
# and Vertex AI access from the service identity (DEPLOY.md). .dockerignore keeps .env,
# key files, eval/, data/ and the frontend out of the build context.

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/srv/venv UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
# Editable install on purpose: the app finds config/ relative to its own source files,
# so the source stays at /srv/backend next to /srv/config.
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin alibi
COPY --from=build /srv/venv /srv/venv
COPY --from=build /srv/backend /srv/backend
COPY config /srv/config
ENV PATH=/srv/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
WORKDIR /srv/backend
USER alibi
EXPOSE 8080
# Migrations are not run here; they run once per release as the owner role (DEPLOY.md).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
