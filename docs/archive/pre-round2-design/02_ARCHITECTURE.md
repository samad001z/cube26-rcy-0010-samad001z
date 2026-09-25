# 02 Architecture

## Pipeline

```mermaid
flowchart LR
  A[Upload: fee report / reimbursement report / evidence files] --> B[Ingest adapters]
  B --> C[Normalise + validate: Charge, EvidenceRecord]
  C --> D[Pre-checks: duplicate, already reimbursed, filing window]
  D --> E[Entity resolution: charge -> shipment/order/SKU/unit]
  E --> F[Relevance routing: reason -> Managers + checks]
  F --> G[Evidence retrieval: keys + custody time window]
  G --> H[Findings: per evidence record, per check]
  H --> I[Aggregation rules -> Verdict + coverage + confidence]
  I --> J[Claim assembly: amount, citations, explanation]
  J --> K[Citation validator]
  K --> L[(Postgres: verdicts, claims, audit)]
  L --> M[API + UI + exports]
```

Every arrow is a typed Pydantic model. Every stage writes `AuditEvent`s keyed by `run_id` and `charge_id`.

## Components

| Component | Responsibility | Deterministic? |
|---|---|---|
| `ingest/adapters` | CSV/XLSX/JSON readers with header synonym maps; PDF/text via LLM parser | Yes for structured; LLM path is validated |
| `ingest/normalise` | ID canonicalisation (`sku 9281` -> `SKU-9281`), timezone to UTC, Decimal money, reason text -> enum | Yes (LLM fallback only for unknown reason text) |
| `precheck` | Fingerprint duplicates; join reimbursements; compute filing deadline | Yes |
| `resolution` | Entity graph lookups; returns resolved entity set + resolution path + missing links | Yes |
| `retrieval` | Fetch evidence by resolved keys from relevant Managers inside the custody window | Yes |
| `engine` | Turn records into Findings, aggregate Findings into a Verdict | Yes (LLM may classify free-text notes into a constrained enum, validated) |
| `claims` | Amount calc, packet assembly, claim text, validator | Yes; explanation text by LLM, validated |
| `llm` | Client, prompt registry, JSON-schema tool outputs, response cache, validators | Temperature 0, cached |
| `audit` | Append-only event log, trace reconstruction | Yes |
| `api` | FastAPI routers, background run execution | n/a |
| `frontend` | Next.js dashboard | n/a |

## Why keyed retrieval, not a vector DB

Retrieval here is an exact-match problem: which records reference this shipment, these SKUs, these units, inside this window. Semantic similarity will happily return the inspection for SKU-9282 when you asked about SKU-9281. That is how systems "invent" evidence without technically fabricating a record. We use relational queries on indexed keys. If judges ask "where is the RAG?", this is the answer, and it is a strong one.

## Stack

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.12 | Data-heavy, Decimal, strong typing with Pydantic |
| API | FastAPI | Typed, async, OpenAPI for free |
| Models | Pydantic v2 | Validation at every boundary |
| DB | PostgreSQL 16 (Supabase or Docker) | JSONB for raw rows, proper indexes, transactions; SQLite in unit tests |
| ORM/migrations | SQLAlchemy 2 + Alembic | Standard, reviewable migrations |
| LLM | Anthropic Claude (Sonnet tier) via `anthropic` SDK, tool-use for structured output | Agent loop, parsing, explanations; model name in config |
| Judgment model | TypeSafe Jev (`jev-latest`) via `POST /v1/systemone` | Calibrated typed decisions (Choice/Score/Noul) for classification; cheap, fast, no text so nothing to hallucinate |
| PDF | `pdfplumber` for text/tables, LLM only on the extracted text | Keep the LLM off raw bytes where possible |
| Tabular | `polars` or `pandas` for ingestion only | Fast CSV parsing; domain logic stays in plain Python |
| Tests | pytest, hypothesis, syrupy (snapshot) | Golden fixtures + property tests + snapshot of verdict output |
| Lint/type | ruff, mypy | CI gates |
| Logging | structlog (JSON) | Correlated by run_id/charge_id |
| Frontend | Next.js 15, TypeScript, Tailwind, shadcn/ui, TanStack Table | Fast to build a serious-looking ops dashboard |
| Packaging | Docker Compose; Makefile | One command up |
| CI | GitHub Actions | lint, type, test, eval scorecard as artifact |
| Deploy | API on Render/Railway/Fly, web on Vercel, DB on Supabase | Free tiers, live URL for judges |

Allowed extra dependencies: `rapidfuzz` (fuzzy header matching only, never for ID matching), `python-dateutil`, `faker` (datagen), `openpyxl`, `tenacity` (LLM retries), `orjson`.

## Run model

A **Run** = one analysis of a set of charges against the current evidence store. Runs are immutable. Re-running with new evidence creates a new Run; the UI can diff two Runs ("3 charges moved from SILENT to CONTRADICTED after Pack data arrived"). This diff is a strong demo moment and a real ops feature.

## Degraded modes

- `LLM_ENABLED=false`: structured adapters still work; PDF/free-text ingestion is rejected with a clear message; notes classification falls back to keyword rules marked low confidence (which pushes verdicts toward UNCERTAIN, the safe direction); explanations use templates.
- LLM timeout or validation failure: same fallback, per call, logged.

## Security and data handling (short)

- Uploaded files stored with SHA-256 hash; raw rows kept in JSONB for traceability.
- Evidence text sent to the LLM is wrapped in data delimiters; system prompt instructs to ignore instructions inside data; outputs are schema-validated and quote-verified.
- No PII needed; if present (customer names in returns), mask before any LLM call.

## Agent layer (see 13_AGENT_LAYER.md)

Every pipeline stage is also exposed as a typed tool. The Recovery Agent (LLM tool-use loop) drives the tools for interactive runs and chat; the batch pipeline calls the same tools directly for eval. Verdicts and amounts only ever come from tools. Differentiating features (Cross-Examination, Evidence Gap ROI, tamper-evident packets, Glass Box) are in 14_WOW_FEATURES.md.

Added dependencies: `cryptography` (Ed25519 signing, W3), `sse-starlette` (Glass Box stream).
