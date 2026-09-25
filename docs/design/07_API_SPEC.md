# 07 API Spec

FastAPI, JSON, OpenAPI at `/docs`. All IDs are strings. Money is `{"amount":"22.80","currency":"USD"}` (string amounts).

## Files and ingestion

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/files` | multipart: `file`, `kind` in {FEE_REPORT, REIMBURSEMENT_REPORT, EVIDENCE_RECEIVING, EVIDENCE_PREP, EVIDENCE_PACK, EVIDENCE_RETURNS, ENTITIES} | `{file_id, sha256, detected_format, header_mapping, rows_parsed, rows_quarantined, warnings[]}` |
| GET | `/api/files` | | list |
| GET | `/api/files/{file_id}/quarantine` | | rows that failed validation with reasons |
| POST | `/api/files/{file_id}/mapping` | `{header_mapping}` | re-parse with confirmed mapping |

Same file uploaded twice (same sha256) is idempotent.

## Runs

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/runs` | `{charge_filter?: {...}, as_of?: date, config_overrides?: {...}}` | `{run_id, status: "QUEUED"}` |
| GET | `/api/runs/{run_id}` | | status, counts by verdict, totals: charged, claimable, expired, reimbursed |
| GET | `/api/runs/{run_id}/decisions?verdict=&reason=&q=&page=` | | paginated decisions |
| GET | `/api/runs/{run_id}/decisions/{charge_id}` | | full Decision + Claim + findings + evidence summaries |
| GET | `/api/runs/{run_id}/decisions/{charge_id}/trace` | | ordered audit events for this charge |
| GET | `/api/runs/{a}/diff/{b}` | | charges whose verdict or amount changed, with before/after |
| GET | `/api/runs/{run_id}/export.csv` | | one row per charge: verdict, claimable, deadline, citations |
| GET | `/api/runs/{run_id}/claims/{claim_id}/packet.zip` | | claim JSON, case text, evidence record JSON files, manifest with sha256 |

Runs execute in a background task; for the hackathon a FastAPI BackgroundTask with a DB status column is enough. Poll `/api/runs/{id}` or use SSE at `/api/runs/{id}/events`.

## Evidence and entities

| Method | Path | Returns |
|---|---|---|
| GET | `/api/evidence/{record_id}` | full record incl. attachments metadata and content hash |
| GET | `/api/entities/shipments/{id}` | shipment with cartons, orders, units, and all evidence referencing it (timeline view) |

## Evaluation

| Method | Path | Returns |
|---|---|---|
| POST | `/api/eval` | runs the golden suite against the eval dataset; returns scorecard |
| GET | `/api/eval/latest` | last scorecard |

## Health and ops

`GET /healthz` (liveness), `GET /readyz` (DB + optional LLM ping), `GET /metrics` (Prometheus text: runs, decisions by verdict, LLM calls, validator failures, stage latency).

## Error shape

```json
{"error": {"code": "UNRESOLVED_ENTITY", "message": "...", "details": {...}, "request_id": "..."}}
```

## Agent

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/agent/runs` | `{file_ids[], instructions?}` | `{run_id}`; agent-driven run |
| GET | `/api/runs/{run_id}/stream` | | SSE: tool calls, rule firings, validations (Glass Box) |
| POST | `/api/agent/chat` | `{run_id, message, history[]}` | `{answer, tool_calls[], cited_record_ids[], verified: bool}` |
| POST | `/api/runs/{run_id}/investigate` | `{charge_ids[] or "all_open"}` | `InvestigationBrief[]` |

## Wow features

| Method | Path | Returns |
|---|---|---|
| POST | `/api/claims/{claim_id}/cross-examine` | `CrossExamination` with UPHELD/REJECTED per objection; claim status after |
| GET | `/api/runs/{run_id}/gaps` | Evidence Gap ROI: ranked gaps with value, charge count, owning Manager; leakage patterns |
| POST | `/api/verify` | multipart packet.zip -> `{valid, checks[], tampered_files[]}` |
| GET | `/api/verify/public-key` | Ed25519 public key (if signing enabled) |
