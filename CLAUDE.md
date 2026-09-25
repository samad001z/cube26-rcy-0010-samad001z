# CLAUDE.md: Alibi (Recovery Manager), Cube Buildathon Round 2

Read this file fully at the start of every session, then `docs/ROUND2_PLAN.md` (current schedule and scope, overrides older docs) and `docs/PROGRESS.md`. Design notes live in `docs/design/` (written before the Round 2 rules were published; where they conflict with this file or ROUND2_PLAN.md, this file wins).

## What we are building

Alibi is an individual Round 2 build of **Recovery Manager** (step 5 of 5). It ingests fee, reimbursement and adjustment reports, matches each charge to upstream evidence from Receiving, Prep, Pack and Returns via `unit_id` (and `fba_shipment_id`, `order_id`), decides whether the evidence contradicts, supports or is insufficient for the charge, and returns a structured, traceable decision: **CLAIM**, **DO NOT CLAIM**, or **REVIEW / UNCERTAIN**, with the amount, the evidence records used, and the reason.

The question every output must answer: *Should this charge be recovered, and can you prove why?*

Deadline: **1 October 2026, 18:00 IST**. No resubmission. All code commits must be made during the build phase (from 25 September 2026, 09:00 IST).

## Decision vocabulary (use exactly these)

- `decision`: `CLAIM` | `DO_NOT_CLAIM` | `REVIEW`
- `evidence_status`: `CONTRADICTED` | `SUPPORTED` | `INSUFFICIENT` | `CONFLICTING`
- Additional outcomes carried in `reason_code`: `DUPLICATE_CHARGE`, `ALREADY_REIMBURSED`, `UNRESOLVED_UNIT`, `NO_RELEVANT_EVIDENCE`, `EVIDENCE_OUTSIDE_WINDOW`, `FILING_WINDOW_EXPIRED`, `FILING_WINDOW_NOT_OPEN` (sourced window not yet open; always REVIEW), `MODEL_UNAVAILABLE` (LLM failed), `DEPENDENCY_UNAVAILABLE` (database or other dependency failed), `ENGINE_ERROR` (the rule engine raised on a charge)
- `status` of a decision record: `final` | `pending` (fail-open) | `overridden`

Mapping (fee lines): CONTRADICTED with full coverage -> CLAIM. SUPPORTED -> DO_NOT_CLAIM. `evidence_status` is always relative to what the line asserts; loss events (lost, damaged, refunded and not returned) are never CLAIM and map per charge type in `config/engine.yaml` `loss_event_outcomes` (D-016). INSUFFICIENT or CONFLICTING -> REVIEW. Duplicate charge -> CLAIM on the duplicate. Already fully reimbursed -> DO_NOT_CLAIM. Sourced filing deadline known and passed -> DO_NOT_CLAIM with `FILING_WINDOW_EXPIRED` (evidence checks still shown). Sourced window not yet open -> REVIEW with `FILING_WINDOW_NOT_OPEN` (D-017).

## Non-negotiable rules

1. **Never invent evidence.** Evidence enters only through ingestion of upstream records.
2. **Deterministic rules decide.** Decisions come from `engine/`. The LLM may: parse unstructured input, classify free-text notes into a fixed enum with a verbatim quote, and write explanations from a decision trace. It never sets a decision, an amount or a citation.
3. **Every LLM output is validated** (quotes are verbatim substrings, every ID and number in an explanation exists in the trace). On failure: discard and fall back.
4. **Batch model calls.** At most one model call per charge covering all its classifications, never one call per field.
5. **Fail open.** If a model, a dependency or the engine fails, persist the input and evidence, set `status: pending`, `decision: REVIEW`, and `reason_code` to `MODEL_UNAVAILABLE` (LLM), `DEPENDENCY_UNAVAILABLE` (database or other dependency) or `ENGINE_ERROR` (engine exception). Never drop a charge.
6. **REVIEW is a first-class outcome**, shown prominently. Never force a CLAIM.
7. **Authoritative rules only.** Fee schedules, dispute windows and requirements come from the channel's published documentation, stored with source URL and retrieval date in `config/rules/`. Never from model memory. Never from the sample CSVs (their amounts and flags are synthetic).
8. **Tenancy isolation.** Postgres row-level security enabled and FORCED on every table, scoped to `organization_id`. Test: `org_demo_bravo` reads zero rows of `org_demo_alpha`, and cannot fetch another org's record or attachment by guessing an ID. Attachment keys are non-guessable.
9. **Money is Decimal.** A claim never exceeds the charge amount minus amounts already reimbursed.
10. **Traceability.** Every decision stores the charge, the resolved unit, the evidence `record_id`s with their `content_hash`, the checks read, the rule that fired, the reason, the model version (if any), and its own `content_hash`. Append-only audit log.
11. **Overrides are data.** A human override stores original decision, new decision, reason, reviewer, timestamp. Never overwrite silently.
12. **Never weaken a test to pass it.** Do not edit fixtures, eval labels or expected outputs to match code. If you think one is wrong, stop and ask the human.
13. **No fake completeness.** No mocks in the eval path, no hardcoded results, no TODO stubs in core paths. Report real command output before claiming anything is done.
14. **No secrets in git.** `.env` is gitignored; `.env.example` has placeholders only.

## Forbidden language (docs, UI, README, LinkedIn)

Do not write: "tamper-proof", "tamper-evident", "immutable", "production-grade", "guaranteed", "autonomous recovery", "works well", "highly accurate", "AI decides". Say what was built: "content hash", "append-only audit log (application-level)", "measured claim precision of X% on N charges".

## Official evidence contract

Use the organisers' official evidence contract as the baseline for upstream records. Fields include `record_id`, `schema_version`, `organization_id`, `client_id`, `agent`, `subject`, `captured_at`, `operator_label`, `images`, `checks` (`check_key`, `verdict`, `confidence`, `detail`, `model_version`, `latency_ms`), `outcome`, `overrides`, `status`, `content_hash`. The sample CSVs in `data/upstream/` are an older flat shape: write an adapter that maps them into the contract shape. Do not invent a different cross-manager contract.

## Interface

- `POST /agent`: main operation (report in, decisions out).
- `GET /health`.
- CLI: `alibi run --report data/fee_report_sample.csv --upstream data/upstream/ --org org_demo_alpha` (headless first, before any UI).

## Stack

Python 3.12 via uv, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL 16 (Docker locally; tests run on Postgres, not SQLite, because RLS must be tested), pytest + hypothesis, Next.js + TypeScript + Tailwind + shadcn/ui for the review UI. LLM via Anthropic SDK behind `llm/client.py`, `LLM_ENABLED=false` by default.

## Layout

```
backend/app/{core,models,db,ingest,adapters,precheck,resolution,retrieval,engine,claims,llm,audit,api}
backend/tests/
eval/            held-out eval set, human labels, eval harness, reports
datagen/         optional adversarial case generator (never imported by backend)
frontend/
config/rules/    authoritative rules with source URLs
docs/            ROUND2_PLAN.md, PROGRESS.md, DECISIONS.md, design/, product/
README.md  ARCHITECTURE.md  CLAUDE.md
```

## Session protocol

1. Read CLAUDE.md, docs/ROUND2_PLAN.md, docs/PROGRESS.md.
2. Plan mode: list the files you will touch and the tests you will write. Wait for approval.
3. Implement in small commits with meaningful messages. Run `make lint test` after each change.
4. Run the step's acceptance check and paste the real output.
5. Update docs/PROGRESS.md, commit, push, stop.

## Dev environment

WSL2 Ubuntu 26.04. Python 3.12 via uv (no system python3.12 package). Node LTS via nvm. Docker Desktop with WSL integration. All commands run in the Ubuntu shell.

## Confirmed by the official handbook (2026-09-25)
- Decision records follow the fixed evidence contract shape: `outcome` = {`decision`, `decided_by`, `decided_at`}; each check = {`check_key`, `verdict` (PASS/FAIL/UNCERTAIN), `confidence`, `detail`, `model_version`, `latency_ms`}; plus `overrides[]`, `status`, `content_hash`.
- Recovery's own checks per charge (examples): `unit_resolved`, `evidence_present`, `evidence_in_custody_window`, `evidence_contradicts_charge`, `not_duplicate`, `not_already_reimbursed`, `amount_computable`. Each gets a verdict and a confidence.
- `confidence` is derived deterministically from the rule path and evidence coverage, documented in ARCHITECTURE.md. Never a number the LLM makes up.
- `decided_by` is `rules@<engine_version>`, or `human:<reviewer>` after an override.
- Evaluation: two humans label the held-out charges independently BEFORE the agent runs; report Cohen's kappa, claim precision, FP, FN, REVIEW rate, latency and cost per charge, failure modes, and a table: charge -> human labels -> agent result -> agree/disagree -> notes.
- LinkedIn post: wait for the official template (27-28 Sep). Tag CodeQuesters and Sydon.AI.
