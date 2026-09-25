# DECISIONS (lightweight ADRs)

### D-001 Rules decide, LLM parses and writes
Status: accepted. Reason: reproducibility, injection resistance, testability. See 06_LLM_LAYER.md.

### D-002 Keyed relational retrieval, no vector store
Status: accepted. Reason: exact entity matching; semantic retrieval causes sibling-SKU false matches.

### D-003 Duplicate charges are claimable
Status: accepted. Reason: the duplicate itself is recoverable; the canonical earlier charge is the evidence.

### D-004 Six verdicts, coverage on CONTRADICTED
Status: accepted. Reason: brief's labels are inconsistent; partial evidence needs a numeric coverage rather than a separate label.

### D-007 Jev for bounded classification, Claude for text and orchestration
Status: superseded (2026-09-25). Jev is dropped for Round 2 (see docs/ROUND2_PLAN.md). Jev returns calibrated probabilities over options we define and generates no text, so it cannot invent evidence or numbers. Used for L3, L4, objection triage and gap ranking with confidence gates; below the gate we escalate to Haiku or to the conservative outcome. Claude keeps the agent loop, parsing and all text.

### Template
### D-00N Title
Status: proposed/accepted. Context. Decision. Consequences.

### D-005 Tool-using agent over deterministic tools
Status: accepted. Context: the brief asks for an agent; the evaluation rewards correctness and traceability. Decision: the agent orchestrates and explains; verdicts and amounts come only from tools; no tool can set a verdict or amount. Consequences: agent and batch pipeline must produce identical results (CI test).

### D-006 Cross-examiner can only add caution
Status: accepted. The adversarial agent may move READY to NEEDS_REVIEW via verified objections; it can never create or increase a claim.

### D-008 Contract shape and CSV adapter choices (csv_v0)
Status: accepted (2026-09-25). Context: the organisers' contract document is not in the repo; only its field names are (CLAUDE.md). Decision: build from those names and log every shape chosen here; reconcile when the document is available.
- `subject` = {unit_id, sku, fnsku, asin, fba_shipment_id, order_id, po_number, po_line, requirements}. `agent` = pod name (receiving, prep, pack, returns). `images` = [{key}] with an HMAC key (D-010). `outcome` is null when the source has no operator verdict. `status` = final | pending | overridden.
- `client_id` has no source column in the CSVs; the adapter sets it to `organization_id`. Assumption.
- Human operator judgments carry no model output: `confidence`, `model_version`, `latency_ms` are null. No number is invented.
- Verdict mapping lives in `config/adapters/csv_v0.yaml`. Only clear-cut values map to PASS/FAIL. Values whose meaning depends on a channel rule (label on seam/curve/edge, warning obscured by fold, expiry illegible after wrap, `signs_of_use`) map to UNCERTAIN with the raw value in `detail`; Day 2 rules judge them against `config/rules/`. Unmapped values quarantine the row.
- `not_required` emits no check (the contract has no N/A verdict). The work-order requirement flags (`wo_polybag`, `wo_suffocation_warning`, `wo_expiry_date`, `wo_handling_marks`) are stored in `subject.requirements` so rules can see what was required without parsing the raw row. The full raw row is also kept in `evidence_records.source`.
- Assumption: prep `original_barcode_covered` = `yes` means the original barcode is covered, which is the compliant state, so `yes` -> PASS.

### D-009 Row-level security
Status: accepted (2026-09-25). Every table has `organization_id NOT NULL`, RLS enabled and FORCED, one policy (`USING` and `WITH CHECK` on `current_setting('app.current_org', true)`). The app connects as `alibi_app` (no superuser, no BYPASSRLS) and sets the org per transaction through `org_session`; with no org set it reads zero rows. `alibi_app` has SELECT and INSERT only, so evidence and `audit_events` cannot be updated or deleted through it. Limitation: the owner role can still modify data, so the audit log is append-only at the application role level, not beyond.

### D-010 Attachment keys
Status: accepted (2026-09-25). Key = HMAC-SHA256(secret, org | record_id | source path). Deterministic (idempotent reloads), not derivable without `ATTACHMENT_KEY_SECRET`, and the raw path is stored only in the RLS-protected `attachments` table.

### D-011 Zero-amount lines: open Day 2 rule question
Status: open. The adapter ingests 0.00 faithfully. For `lost_inbound` and `damaged_in_warehouse`, 0.00 can mean the channel paid no reimbursement for a lost or damaged unit, which may itself be recoverable. 9 of the 61 sample lines are 0.00 (including non-loss types such as FEE-0014-2). Amount 0 must not be treated as "nothing to recover" by default. Decide per charge_type on Day 2, from the published rules.

### D-012 Eval set
Status: accepted. We build our own held-out set, labelled independently by two humans before the agent runs (Round 2 README and the official handbook). No organiser issue needed.
