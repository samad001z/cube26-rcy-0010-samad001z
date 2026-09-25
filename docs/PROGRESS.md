# PROGRESS (context carry between sessions)

Update at the end of every session. Newest entry on top.

### 2026-09-25 - Day 2 fixes, branch `day2-fixes`
- Done:
  - Task 1 (D-016): claim direction for loss events. `evidence_status` is now always relative to what the line asserts; lost inbound and damaged in warehouse were inverted. Loss events map per charge type through `config/engine.yaml` `loss_event_outcomes` (one commented row each) and are never CLAIM. A refund counts as returned complete only when identity, parts and condition all PASS; anything else is REVIEW, "possible separate claim". A lost unit seen later is REVIEW, `R_LOSS_DOUBTFUL`. A known passed deadline on a loss event is DO_NOT_CLAIM, `FILING_WINDOW_EXPIRED`. Next actions on refuting rows never steer towards claiming.
  - Task 2 (D-017): the first sourced rule values, from the 2024 Seller Central announcement pasted by the human lead (caveat: may be superseded). Damaged in warehouse closes at 60 days; refund, item not returned, opens at 60 and closes at 120; the two removal-claim rules are stored under `unmapped_rules`. `posted_date` stands in for the source's event date, and every reason says so. New rule 1 `R_FILING_WINDOW_NOT_OPEN`: REVIEW, `FILING_WINDOW_NOT_OPEN`.
  - Task 3: the CLI prints "routing confidence" (defined in ARCHITECTURE.md). `evidence_in_custody_window` is UNCERTAIN "no relevant evidence to check" when `evidence_present` is FAIL. A missing setting prints one line ("copy .env.example to .env") and exits 2.
  - `ENGINE_VERSION` is now 0.3.0.
- Reviews:
  - test-guardian: 7 of 8 mutations were caught; the 8th was refused by config validation. Added the missing "parts not recorded" test and removed a `type: ignore`.
  - rules-guardian: no breach of the core rules. Folded in: damaged is SUPPORTED only with every prep check PASS; a lost-inbound sighting needs identity PASS; the validator refuses any CLAIM on a loss event; next actions reworded, with a case-insensitive guard test; stale rule numbers fixed.
- Tests/eval status:
  - `make lint test` green, 217 passed on Postgres 16.
  - `alibi run` as of 2026-09-25: alpha 40 lines = 0 CLAIM, 1 DO_NOT_CLAIM (FEE-0071-2, deadline passed), 39 REVIEW. Bravo 21 lines = 0 CLAIM, 1 DO_NOT_CLAIM (FEE-0048-2, item returned complete), 20 REVIEW.
  - Regression snapshot re-approved by the human lead (it is not ground truth). No eval yet.
- Open issues:
  - Still unsourced: filing windows for lost inbound and both fee types, and the fee schedule.
  - The `posted_date` proxy is an assumption until a report carries the event date.
  - The refund custody window (60 days either side of posting) is narrower than the 60-120 day filing window. A return arriving between 60 and 120 days after posting would be outside the custody window (REVIEW). Revisit with the eval set.
  - With an unresolved unit, `evidence_present` shows PASS with the resolution failure as detail. Pre-existing, left as is; flag for Day 3.
  - Official contract document still missing (D-008).
- Environment: Docker is not available in this cloud session. Postgres 16 ran from the container's own install (`/usr/lib/postgresql/16`) using `docker/postgres/init.sh`. No repo change.
- Next step: Day 3: held-out eval set labelled by two humans BEFORE the agent runs, eval harness, POST /agent.

### 2026-09-25 - Day 2 (P4-P7, headless CLI), branch `day2-engine`
- Done: pre-checks (duplicate fingerprint, already-reimbursed heuristic, filing window from sourced rules only), unit resolution, retrieval with custody windows, rule engine (8 handbook checks, 17 ordered rules, deterministic confidence), Decimal claim amounts, citation validator re-reading from Postgres (fails closed to REVIEW/pending), `decisions` table (migration 0002, forced RLS, append-only), fail-open per charge, audit events, `alibi run` and `make run ORG=...`. Decisions D-011 (resolved), D-013 (Option C defect_category), D-014 (filing window), D-015 (engine choices). ARCHITECTURE.md started (decision path, rules, confidence).
- Reviews: rules-guardian found 2 rule-9 breaches in refund matching (a refunded duplicate was claimed again; one fee absorbed refunds of other shipments). Both are reproduced in tests and fixed, and ambiguous refunds now go to REVIEW. Its suggestions were applied: fail-open hardening, a reason code on dependency errors (now DEPENDENCY_UNAVAILABLE, D-015c), non-final records treated as uncertain, validator scope and reimbursement checks, bool rule values refused. test-guardian found no weakened tests but a loose CLI test; that test now checks every printed block against the stored decision for both orgs. It also led to a sample rule-count snapshot (regression only).
- Human decisions after review: D-015a (a passed deadline is DO_NOT_CLAIM with FILING_WINDOW_EXPIRED), D-015b accepted, D-015c (new reason codes DEPENDENCY_UNAVAILABLE and ENGINE_ERROR; CLAUDE.md vocabulary updated). The sample snapshot is approved as a regression check (`test_regression_snapshot_sample`); it is not ground truth and is excluded from eval metrics.
- Tests/eval status: `make lint test` green, 182 tests on Postgres 16. Hypothesis: 200 examples each for the claim cap and the engine invariants (including "engine output always passes the validator"). Mutation check: disabling validator enforcement fails 2 tests. Acceptance: `alibi run` decided and printed 40/40 alpha and 21/21 bravo lines, each with evidence, checks and reason. All 61 are REVIEW: 42 weight-tier with no measurements (NO_RELEVANT_EVIDENCE), 10 loss events (D-011), 7 inbound defect fees with all prep checks passed but no defect_category (D-013), 2 inbound defect fees with an UNCERTAIN label/barcode check. No eval yet.
- Open issues: all channel rule values in `config/rules/amazon_us.yaml` are null. This environment's egress policy blocks sellercentral.amazon.com, so the human lead will paste verbatim excerpts: a filing window for each of the 5 charge types, and the fulfilment fee schedule. Until then every decision carries "filing deadline not verified". The sample has no `defect_category`, so no sample line can be CLAIM. The branch is pushed to origin (the fork). Docker Hub rate-limited `postgres:16` in the cloud session; the image was pulled from `mirror.gcr.io/library/postgres:16` and tagged locally (no repo change). The official contract document is still missing (D-008).
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
