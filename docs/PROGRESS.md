# PROGRESS (context carry between sessions)

Update at the end of every session. Newest entry on top.

### 2026-09-25 - Day 2 (P4-P7, headless CLI), branch `day2-engine`
- Done: pre-checks (duplicate fingerprint, already-reimbursed heuristic, filing window from sourced rules only), unit resolution, retrieval with custody windows, rule engine (8 handbook checks, 16 ordered rules, deterministic confidence), Decimal claim amounts, citation validator re-reading from Postgres (fails closed to REVIEW/pending), `decisions` table (migration 0002, forced RLS, append-only), fail-open per charge, audit events, `alibi run` and `make run ORG=...`. Decisions D-011 (resolved), D-013 (Option C defect_category), D-014 (filing window), D-015 (engine choices). ARCHITECTURE.md started (decision path, rules, confidence).
- Tests/eval status: `make lint test` green, 163 tests on Postgres 16. Hypothesis: 200 examples each for the claim cap and the engine invariants (including "engine output always passes the validator"). Mutation check: disabling validator enforcement fails 2 tests. Acceptance: `alibi run` decided and printed 40/40 alpha and 21/21 bravo lines, each with evidence, checks and reason. All 61 are REVIEW: 42 weight-tier with no measurements (NO_RELEVANT_EVIDENCE), 10 loss events (D-011), 7 inbound defect fees with all prep checks passed but no defect_category (D-013), 2 inbound defect fees with an UNCERTAIN label/barcode check. No eval yet.
- Open issues: all channel rule values in `config/rules/amazon_us.yaml` are null. This environment's egress policy blocks sellercentral.amazon.com, so the human lead will paste verbatim excerpts: a filing window for each of the 5 charge types, and the fulfilment fee schedule. Until then every decision carries "filing deadline not verified". The sample has no `defect_category`, so no sample line can be CLAIM. Docker Hub rate-limited `postgres:16` in the cloud session; the image was pulled from `mirror.gcr.io/library/postgres:16` and tagged locally (no repo change). The official contract document is still missing (D-008).
- Next step: Day 3: held-out eval set labelled by two humans BEFORE the agent runs, eval harness, POST /agent.

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
