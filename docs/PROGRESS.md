# PROGRESS (context carry between sessions)

Update at the end of every session. Newest entry on top.

### 2026-09-25 - Day 1 (P0 + P1)
- Done: backend scaffold (FastAPI `/health`, Postgres 16 in docker-compose with `alibi_owner`/`alibi_app` roles, CI workflow, Makefile). Contract and charge models, content hashing, Decimal money. CSV-to-contract adapter with a reviewable mapping file and quarantine. Alembic schema with forced RLS on all 6 tables, org-scoped sessions, `alibi ingest` CLI. Decisions D-008 to D-012.
- Tests/eval status: `make lint test` green, 63 tests (19 in the Postgres isolation file). A mutation check (RLS removed from one table) made 6 tests fail. No eval yet.
- Open issues: `.env.example` not written (the `Read(./.env.*)` deny rule blocks that filename). Official contract document still missing (D-008). Zero-amount rule (D-011). CI workflow not yet run on GitHub. Nothing pushed.
- Next step: Day 2: pre-checks, unit resolution, evidence retrieval, rule engine, claims and citation validator, `alibi run`.

## Template
### YYYY-MM-DD HH:MM - Phase Pn
- Done:
- Tests/eval status:
- Open issues:
- Next step:
