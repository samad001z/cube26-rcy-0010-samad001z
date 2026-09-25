# 12 Production Readiness

Judges hiring for a real company will look for these. Tick every box you can; mention the rest as roadmap.

## Correctness and safety
- [ ] Citation validator blocks every unverified claim
- [ ] False-claim-rate gate in CI
- [ ] Decimal money, currency always attached
- [ ] Idempotent file ingestion by sha256
- [ ] Immutable runs; re-runs create new runs; run diff
- [ ] Quarantine for malformed rows (never silently dropped)
- [ ] Filing windows configurable and applied

## Observability
- [ ] structlog JSON logs with run_id, charge_id, stage
- [ ] `/metrics` Prometheus endpoint: decisions by verdict, stage latency histograms, LLM calls, LLM validator failures, cache hit rate
- [ ] Per-run summary with stage timings and counts
- [ ] Full per-charge trace from audit log

## Reliability
- [ ] LLM calls: timeouts, retries with backoff, cache, fallback path
- [ ] System fully usable with `LLM_ENABLED=false`
- [ ] DB migrations with Alembic; `make migrate` idempotent
- [ ] Health and readiness endpoints

## Security
- [ ] Secrets only via env; `.env.example` committed, `.env` ignored
- [ ] Upload limits (size, type), filename sanitisation
- [ ] Evidence text treated as untrusted; prompt-injection tests in CI
- [ ] PII masking before LLM calls
- [ ] Audit table append-only (DB role cannot UPDATE/DELETE)
- [ ] CORS locked to the frontend origin
- [ ] Simple API key or Supabase auth for the deployed demo

## Deployability
- [ ] `docker compose up` brings db, api, web from a clean clone
- [ ] Deployed: API (Render/Railway/Fly), web (Vercel), DB (Supabase)
- [ ] Seed script for the demo dataset against the deployed DB
- [ ] README quickstart verified on a fresh machine by a teammate

## Maintainability
- [ ] Rules and relevance table in YAML config, versioned; run stores config hash
- [ ] Prompts versioned files; run stores prompt versions
- [ ] Evidence contract (`EvidenceRecord`) documented as the integration point for other Managers
- [ ] ADRs in `docs/DECISIONS.md`

## Roadmap slide (say it, do not build it)
- Direct SP-API ingestion (Reports + Finances APIs) on a schedule
- Auto-filing of cases via Seller Central case APIs where available, with human approval
- Learning which claim types actually get paid, feeding back into confidence
- Multi-marketplace adapters (Flipkart, Meesho, Shopify 3PLs)
