# Architecture

Status: partial. This file covers the decision path built on Day 2. Components, deployment, the review UI and the LLM layer are added on later days.

## Decision path (one organisation, one run)

```
alibi run --report ... --upstream ... --org ...
  ingest (idempotent)      adapters/csv_v0 -> charges, evidence_records (contract shape, content_hash)
  pipeline.run_org         one org-scoped session: RLS applies to every read and write
    precheck               duplicate fingerprint, already-reimbursed heuristic, filing window
    resolution             charge -> unit_id; fails naming the missing or conflicting key
    retrieval              relevant pods per charge type; scope (shipment/order) and custody window
    engine.assess          what the usable records say about this charge type
    engine.decide          8 checks, ordered rules, claim amount, citations -> DecisionRecord
    claims.validator       re-reads every citation from Postgres; fails closed to REVIEW/pending
    persist + audit        decisions row (append-only), DECISION audit event
```

If deciding one charge raises, that charge is still persisted as REVIEW with status `pending` (rule `R_ENGINE_ERROR`; `reason_code` `DEPENDENCY_UNAVAILABLE` if the database or another dependency failed, `ENGINE_ERROR` otherwise), inside a savepoint so the rest of the run continues. A pre-check failure fails open every charge of the run.

Configuration:
- `config/rules/amazon_us.yaml`: channel rules only. A value needs a source URL, a retrieval date, `retrieved_by: human` and a verbatim excerpt, or the loader refuses it. Unsourced values are null. Filing windows have an open and a close day counted from the line's posted date, used as a proxy for the event date the source counts from (D-017).
- `config/engine.yaml`: this project's engineering choices (charge kinds, relevance, custody windows, defect category coverage, duplicate window, confidence table). See docs/DECISIONS.md D-011, D-013, D-014, D-015.

## Checks on every decision

| check_key | PASS | FAIL | UNCERTAIN |
|---|---|---|---|
| `unit_resolved` | a record carries the unit and sku/fnsku agree | no record, or a key conflicts | - |
| `not_duplicate` | no earlier line with the same fingerprint | duplicate of an earlier line | - |
| `not_already_reimbursed` | no, or partial, matching reimbursement | fully reimbursed, or the line is itself a reimbursement | a refund could belong to more than one fee |
| `within_filing_window` | inside the sourced window | window not open yet ("not yet eligible"), or sourced deadline passed | no sourced deadline ("filing deadline not verified") |
| `evidence_present` | a usable record speaks to the charge | nothing speaks to it | - |
| `evidence_in_custody_window` | an in-scope record that speaks to the charge is inside the window | in-scope records exist, none inside | no in-scope record, or none speaks to the charge ("no relevant evidence to check") |
| `evidence_contradicts_charge` | CONTRADICTED | SUPPORTED | INSUFFICIENT or CONFLICTING |
| `amount_computable` | full fee is the claim basis | the amount needs a unit value or an unsourced fee schedule | - |

## Rules (first match wins)

`evidence_status` is always relative to what the line asserts: CONTRADICTED means the evidence says the line is wrong (D-016). For a fee that favours recovery. For a loss event the line is what the seller would be reimbursed for, so SUPPORTED favours recovery and CONTRADICTED makes the loss doubtful.

| # | rule_id | decision | key check |
|---|---|---|---|
| 1 | R_FILING_WINDOW_NOT_OPEN | REVIEW (`FILING_WINDOW_NOT_OPEN`); never CLAIM or DO_NOT_CLAIM | within_filing_window |
| 2 | R_FEE_REFUND_LINE | DO_NOT_CLAIM | not_already_reimbursed |
| 3 | R_ZERO_FEE | DO_NOT_CLAIM | amount_computable |
| 4 | R_REIMBURSEMENT_AMBIGUOUS | REVIEW | not_already_reimbursed |
| 5 | R_DUPLICATE | CLAIM (DO_NOT_CLAIM, `FILING_WINDOW_EXPIRED`, if the sourced deadline passed) | not_duplicate |
| 6 | R_ALREADY_REIMBURSED | DO_NOT_CLAIM | not_already_reimbursed |
| 7 | R_UNRESOLVED_UNIT | REVIEW | unit_resolved |
| 8 | R_EVIDENCE_OUTSIDE_WINDOW | REVIEW | evidence_in_custody_window |
| 9 | R_NO_RELEVANT_EVIDENCE | REVIEW | evidence_present |
| | *Loss events only, never CLAIM* | | |
| 10 | R_FILING_WINDOW_PASSED | DO_NOT_CLAIM (`FILING_WINDOW_EXPIRED`) | within_filing_window |
| 11 | R_CONFLICTING | REVIEW | evidence_contradicts_charge |
| 12 | R_INSUFFICIENT | REVIEW | evidence_contradicts_charge |
| 13 | row of `loss_event_outcomes` (below) | REVIEW or DO_NOT_CLAIM | see below |
| | *Fees only* | | |
| 14 | R_CONFLICTING | REVIEW | evidence_contradicts_charge |
| 15 | R_SUPPORTED | DO_NOT_CLAIM | evidence_contradicts_charge |
| 16 | R_INSUFFICIENT | REVIEW | evidence_contradicts_charge |
| 17 | R_AMOUNT_NOT_COMPUTABLE | REVIEW | amount_computable |
| 18 | R_PARTIAL_COVERAGE | REVIEW | evidence_contradicts_charge |
| 19 | R_DEFECT_CATEGORY_MISSING | REVIEW | evidence_contradicts_charge |
| 20 | R_FILING_WINDOW_PASSED | DO_NOT_CLAIM (`FILING_WINDOW_EXPIRED`) | within_filing_window |
| 21 | R_CONTRADICTED_FULL | CLAIM | evidence_contradicts_charge |


Loss-event rows (`config/engine.yaml` `loss_event_outcomes`, D-016):

| charge type | outcome | evidence_status | decision | rule_id |
|---|---|---|---|---|
| refund, item not returned | ordered item back; identity, parts, condition all PASS | CONTRADICTED | DO_NOT_CLAIM | R_ITEM_RETURNED |
| refund, item not returned | ordered item back; incomplete, damaged or condition uncertain | CONTRADICTED | REVIEW (possible separate claim) | R_RETURNED_INCOMPLETE_OR_DAMAGED |
| refund, item not returned | a different item came back | SUPPORTED | REVIEW until an amount is computable | R_AMOUNT_NOT_COMPUTABLE |
| lost inbound | prep on the shipment, no later record of the unit | SUPPORTED | REVIEW until an amount is computable | R_AMOUNT_NOT_COMPUTABLE |
| lost inbound | a final customer return of the unit after the loss, identity PASS | CONTRADICTED | REVIEW (loss doubtful) | R_LOSS_DOUBTFUL |
| damaged in warehouse | final prep with at least one check, every check PASS | SUPPORTED | REVIEW until an amount is computable | R_AMOUNT_NOT_COMPUTABLE |

Only the "until an amount is computable" rows suggest an override with an amount. The validator also refuses any CLAIM on a loss event. A refund line with no returns record in the custody window is rule 9, `R_NO_RELEVANT_EVIDENCE` (INSUFFICIENT); its reason notes that the absence is consistent with the seller's claim but is not evidence.

After the engine: `R_CITATION_INVALID` (validator) or `R_ENGINE_ERROR` (exception), both REVIEW with status `pending`.

## Routing confidence (deterministic)

Each check carries a `confidence`, and the decision carries the confidence of its rule's key check. The CLI and UI label the decision's value **routing confidence**: how directly the ingested inputs determine the check the rule rests on, and so how firmly the line was routed to CLAIM, DO_NOT_CLAIM or REVIEW. It is not a probability that the decision is right, and not a probability that the channel accepts a claim. Measured accuracy comes only from the held-out, human-labelled eval set.

It comes from a fixed table in `config/engine.yaml`. It is never produced by a model. The contract field keeps the name `confidence`.

| source of the verdict | confidence |
|---|---|
| exact comparison of ingested keys, date arithmetic, Decimal arithmetic | 1.00 |
| a human operator's recorded check (prep, returns) | 0.90 |
| CONTRADICTED on `evidence_contradicts_charge` | 0.90 x unit coverage (e.g. 0.45 for 1 of 2 units) |
| a charge that failed open | 0.00 |

The decision's routing confidence is the confidence of its rule's key check (table above). Example: 1.00 on `R_NO_RELEVANT_EVIDENCE` means "no record carries the data" was established by exact key comparison; it says nothing about whether the charge is recoverable.

## Decision record

Contract fields (`record_id`, `schema_version` = `recovery_v1`, `organization_id`, `client_id`, `agent` = `recovery`, `subject`, `captured_at`, `checks`, `outcome` {decision, decided_by = `rules@<engine_version>`, decided_at}, `overrides`, `status`, `content_hash`), plus: `decision`, `evidence_status`, `reason_code`, `rule_id`, `rule_path`, `reason`, `warnings`, `next_action`, `confidence`, `coverage`, `amount_charged`, `amount_reimbursed`, `claim` {amount, currency, computation lines}, `citations` [{kind, id, content_hash, role, check_keys}], `evidence_considered` (every record read, usable or not, and why), `resolved_unit`, `engine_version`, `rules_hash`, `config_hash`, `model_version` (null: no model is used).

`content_hash` is sha256 over canonical JSON of the record (sorted keys, Decimals as strings, no floats). Decisions and audit events are append-only for the application role (SELECT and INSERT only); the owner role can still modify rows, so append-only holds at the application role level only.
