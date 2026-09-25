#!/usr/bin/env bash
# Creates the two roles and the dev/test databases.
#   alibi_owner: owns the schema and tables, runs migrations.
#   alibi_app:   what the application connects as. Not a superuser, no BYPASSRLS,
#                so row-level security always applies to it.
# Runs inside the postgres container on first start, and in CI against the
# service container (PGHOST/PGPASSWORD set by the workflow).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname postgres \
  -v owner_pw="${ALIBI_OWNER_PASSWORD}" -v app_pw="${ALIBI_APP_PASSWORD}" <<'SQL'
CREATE ROLE alibi_owner LOGIN PASSWORD :'owner_pw' NOSUPERUSER NOCREATEROLE NOBYPASSRLS;
CREATE ROLE alibi_app   LOGIN PASSWORD :'app_pw'   NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS;
CREATE DATABASE alibi      OWNER alibi_owner;
CREATE DATABASE alibi_test OWNER alibi_owner;
SQL

for db in alibi alibi_test; do
  psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname "$db" <<'SQL'
ALTER SCHEMA public OWNER TO alibi_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO alibi_app;
SQL
done
