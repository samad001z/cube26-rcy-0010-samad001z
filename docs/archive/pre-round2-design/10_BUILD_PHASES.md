# 10 Build Phases

Each phase has a goal, a copy-paste prompt for the coding agent, and acceptance criteria. Do not start a phase until the previous one's criteria pass. After every phase: `make lint test eval`, update `docs/PROGRESS.md`.

Priority tiers, so the plan survives whatever the hackathon duration turns out to be:
- **MUST** (a credible submission): P0-P7, P9, P9A (agent), P10 (charges table + detail), P11 (scorecard)
- **SHOULD** (production-grade feel + differentiation): P8, P10 (diff, timeline), P12, P14 (W4 Glass Box, W3 packets, W2 Gap ROI, W1 Cross-Examination)
- **COULD** (polish): PDF/email ingestion, Ed25519 signing, stress profile

How to drive each phase with Claude Code: see `15_CLAUDE_CODE_WORKFLOW.md` (use `/phase Pn` and `/checkpoint`).

Suggested team split for 4 people: A = engine + claims (P5-P7), B = datagen + fixtures + eval (P2, P11), C = ingestion + API + LLM (P3, P8, P9), D = frontend + deploy + demo (P10, P12, P13). A owns `CLAUDE.md` rules and reviews every PR that touches `engine/` or `claims/`.

---

## P0 Scaffold

**Prompt**
> Read CLAUDE.md and docs/02_ARCHITECTURE.md. Scaffold the monorepo exactly as the layout in CLAUDE.md. Backend: Python 3.12 project with pyproject (uv or poetry), FastAPI app with /healthz and /readyz, pydantic-settings config, structlog JSON logging, ruff + mypy config, pytest config. Frontend: Next.js 15 TS app with Tailwind and shadcn/ui initialised. docker-compose with postgres:16, api, web. Makefile targets: install, dev, lint, test, eval, seed, migrate. GitHub Actions workflow running lint, mypy, pytest. Create docs/PROGRESS.md and docs/DECISIONS.md. No domain code yet.

**Done when**: `docker compose up` serves `/healthz` 200 and the Next.js page; CI green on an empty test.

## P1 Domain models + DB

**Prompt**
> Implement every model in docs/03_DATA_MODEL.md under backend/app/models, plus core/money.py (Money type with Decimal, currency, quantise helper, arithmetic that refuses mixed currencies) and core/ids.py (canonicalisers for SKU, shipment, order ids per docs/04_DATASETS.md messiness section). Create SQLAlchemy tables and the first Alembic migration with the indexes listed. Add a repository layer with typed read/write functions. Unit tests for Money and id canonicalisation, including edge cases.

**Done when**: migration applies on a clean DB; Money tests cover rounding, mixed currency error, negative handling; id tests cover every variant listed.

## P2 Synthetic data generator + ground truth

**Prompt**
> Implement datagen/ per docs/04_DATASETS.md. Seeded, profiles demo/eval/stress. Generate in the physical order listed. Implement every scenario injector S1-S8 and X1-X10 as separate functions, each appending ground truth lines. Emit files in realistic formats: reimbursement report with Amazon GET_FBA_REIMBURSEMENTS_DATA headers, fee report in a settlement-style layout, evidence per Manager as CSV/JSON, entities as JSON. Apply the messiness rules. The backend must never import datagen. Write datagen/README.md explaining each scenario.

**Done when**: `make seed` writes `data/demo` and `data/eval`; ground truth has one line per charge; same seed gives byte-identical output; a script prints scenario counts.

## P3 Ingestion

**Prompt**
> Implement ingest/ adapters for CSV, XLSX and JSON. Header mapping via config/header_synonyms.yaml with rapidfuzz only for header names (never for IDs). Normalise ids, dates (to UTC), money (Decimal), reason text (via config/reason_synonyms.yaml; leave UNKNOWN if unmapped, LLM comes in P8). Every parsed row keeps a SourceRef with file sha256 and row locator. Invalid rows go to quarantine with explicit reasons. Idempotent by file sha256. Expose POST /api/files and GET /api/files/{id}/quarantine.

**Done when**: all demo and eval files ingest; malformed rows from X10 are quarantined with correct reasons; re-uploading a file is a no-op.

## P4 Pre-checks

**Prompt**
> Implement precheck/: duplicate fingerprinting per docs/05_DECISION_ENGINE.md, reimbursement ledger matching (by related_charge_id, then case_id, then order/shipment+sku+reason), filing deadline computation from config/dispute_windows.yaml. Pure functions with tests from fixtures S7, S8, X5.

**Done when**: S7, S8, X5 prechecks produce the expected intermediate outputs.

## P5 Entity resolution + retrieval

**Prompt**
> Implement resolution/ (charge -> resolved scope: shipment, cartons, order, skus, units, custody window; or a structured failure naming the missing link) and retrieval/ (relevance routing from config/relevance.yaml; fetch evidence by scope keys; batch by shipment for performance; classify each record as in-window or out-of-window with reason). No verdict logic here. Tests from fixtures S4, S5, X1, X2.

**Done when**: X2 retrieves nothing for the charged SKU; X1 returns the record marked out-of-window; S5 routes to PACK.

## P6 Findings + aggregation engine

**Prompt**
> Implement engine/: findings per record per check (docs/05 findings section), numeric checks (quantity, size tier with noise margin), aggregation rules R0-R11 in order, R_REIMBURSED post-rule, confidence derivation, missing_evidence generation. Every rule has an id and a docstring. Rules are pure. Notes are ignored in this phase (LLM classification arrives in P8; for now notes produce NEUTRAL). Write fixture tests for every scenario.

**Done when**: all golden fixtures S1-S8, X1-X8 pass on verdict, coverage, rule_path.

## P7 Claims + validator

**Prompt**
> Implement claims/: amount calculation exactly as docs/05 (Decimal, computation lines), claim assembly, Citation with content hashes and field paths, citation validator (existence, hash match, scope, window), template explanation and template case text. A claim that fails validation is not persisted and the decision becomes UNCERTAIN with reason CITATION_VALIDATION_FAILED. Add hypothesis property tests for invariants 1-9 in docs/09.

**Done when**: all fixtures pass on claimable and citations; property tests pass with 200 examples.

## P8 LLM layer

**Prompt**
> Use the TypeSafe skill for the Jev parts. Implement llm/jev_client.py per docs/16_JEV_INTEGRATION.md (batched questions per call, confidence gates, fallback to Haiku, audit events, cassettes). Then implement llm/ per docs/06: client with tool-use structured output, temperature 0, retries, Postgres cache, prompt registry with versioned prompt files, validators (quote, explanation, enum). Wire L3 reason normalisation into ingestion for UNKNOWN reasons, L4 notes classification into findings (validated, INDIRECT strength only), L5 explanations and L6 case text into claims with template fallback, L1 PDF/email parsing as a new adapter. LLM_ENABLED flag. Record cassettes for tests. Add X9 injection fixture test.

**Done when**: X9 passes (verdict unchanged, flag raised); with LLM_ENABLED=false everything except L1 still works; validator failure rate reported.

## P9 Pipeline + API

**Prompt**
> Implement pipeline.py orchestrating a Run end to end with audit events at every stage, and the API in docs/07 (runs, decisions, trace, diff, export.csv, evidence, entities, eval, metrics). Background execution with status polling. Error shape as specified.

**Done when**: full demo dataset runs via API; trace endpoint reconstructs every stage for a charge; diff works between two runs.

## P9A Recovery Agent

**Prompt**
> Read docs/13_AGENT_LAYER.md. Implement agent/: tool registry generating JSON schemas from the Pydantic input/output models of the existing pipeline functions (no new decision logic), the Anthropic tool-use loop with budgets and timeouts, the system prompt file, AGENT audit events, the run summary numeric validator, Ask Recovery chat endpoint, and the Investigator with InvestigationBrief output (potential_value via compute_claim with assume_coverage=1). There must be no tool that sets a verdict, edits evidence, or writes an amount. Add tests: agent-vs-pipeline equality on the demo dataset (use recorded cassettes), injection file test, numeric honesty test.

**Done when**: agent run and batch run produce identical decisions on demo data; chat answers cite record IDs; Investigator briefs generated for all SILENT/UNCERTAIN demo charges.

## P10 Frontend

**Prompt**
> Build the screens in docs/08_FRONTEND_SPEC.md in this order: Charges Table, Charge Detail, Run Overview, Data Sources, Scorecard, Shipment Timeline, Run Diff. Typed API client generated from OpenAPI. Every ID is a link. No verdict relabelling in the UI.

**Done when**: a judge can go from upload to a claim's evidence chain in under 60 seconds without explanation.

## P11 Eval harness + scorecard

**Prompt**
> Implement backend/scripts/eval.py: run the pipeline on data/eval, compare to ground_truth.jsonl, compute every metric in docs/09, write reports/scorecard.md and .json, exit non-zero if false claim rate > 0 or verdict accuracy < 97%. Wire into CI and the /api/eval endpoint.

**Done when**: scorecard renders in CI artifacts and in the UI; gates enforced.

## P12 Deploy + ops

**Prompt**
> Implement /metrics, PII masking before LLM calls, upload limits, CORS, append-only audit role, simple API key auth. Deploy API, web and DB per docs/12. Seed the demo dataset on the deployed DB. Verify quickstart on a fresh clone.

**Done when**: public URL works end to end; docs/12 checklist ticked.

## P14 Wow features

Build in this order, each as its own session: W4 Glass Box, W3 tamper-evident packets, W2 Evidence Gap ROI, W1 Cross-Examination. Spec: docs/14_WOW_FEATURES.md.

**Prompt (per feature)**
> Read docs/14_WOW_FEATURES.md section <W#> and docs/13_AGENT_LAYER.md. Implement the backend, the API endpoints listed in docs/07 for it, the UI listed in docs/08 for it, and the eval or tests listed for it. W1 cross-examiner may only move a claim from READY to NEEDS_REVIEW; every objection type except OTHER must have a deterministic verifier.

**Done when**: W4 streams a live run; W3 /verify detects a one-character tamper; W2 report sums match decision data exactly; W1 detects 100% of planted verifiable weaknesses and raises zero upheld objections on S1.

## P13 Demo polish

Follow `11_DEMO_AND_PITCH.md`. Rehearse the live re-run with Returns data at least three times. Record a backup video.
