# DECISIONS (lightweight ADRs)

### D-001 Rules decide, LLM parses and writes
Status: accepted. Reason: reproducibility, injection resistance, testability. See docs/archive/pre-round2-design/06_LLM_LAYER.md (history only).

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
Status: accepted (2026-09-25). Key = HMAC-SHA256(secret, org | agent | record_id | source path) (agent added by D-018). Deterministic (idempotent reloads), not derivable without `ATTACHMENT_KEY_SECRET`, and the raw path is stored only in the RLS-protected `attachments` table.

### D-011 Zero-amount lines
Status: accepted (2026-09-25, approved by the human lead). Each `charge_type` has a `kind` in `config/engine.yaml`.
- `fee` (`inbound_defect_fee`, `fulfilment_fee_weight_tier`): the amount is money taken. A fee of 0.00 has nothing to recover: DO_NOT_CLAIM, rule `R_ZERO_FEE`.
- `loss_event` (`lost_inbound`, `damaged_in_warehouse`, `refund_issued_item_not_returned`): the amount is the reimbursement already paid; 0.00 means nothing was paid, not that nothing is owed. What is owed needs an authoritative unit value that no upstream record provides, so `amount_computable` = FAIL and the line is REVIEW (`R_AMOUNT_NOT_COMPUTABLE`), never CLAIM, whatever the evidence says. The evidence status is still computed and shown (e.g. CONFLICTING on FEE-0064-1).
- Rule 9 is unchanged: a claim never exceeds charge minus amounts already reimbursed.

### D-012 Eval set
Status: accepted. We build our own held-out set, labelled independently by two humans before the agent runs (Round 2 README and the official handbook). No organiser issue needed.

### D-013 Inbound defect fees need a defect category to be claimed (Option C)
Status: accepted (2026-09-25, approved by the human lead). The fee report gets an optional `defect_category` column (absent in the csv_v0 sample). `config/engine.yaml` maps each category to the prep checks that can show that defect was not present (e.g. `label` -> `fnsku_label_placement`, `original_barcode_covered`).
- CLAIM only when `defect_category` is present, mapped, and every covering prep check PASSes in a final prep record inside the custody window, with full unit coverage.
- Category absent and every prep/label check passes: REVIEW, evidence_status CONTRADICTED (scope: prep/label only), rule `R_DEFECT_CATEGORY_MISSING`, next action: confirm the defect type in Seller Central, then override.
- Any in-scope prep check FAIL: SUPPORTED, DO_NOT_CLAIM. With no category, the scope is all prep/label checks, so a FAIL on any of them counts. Assumption: a recorded prep defect makes the fee plausible; a human can override.
- A category not in the mapping, an UNCERTAIN verdict, a covering check that was not recorded, or a pending record: INSUFFICIENT, REVIEW.
- Consequence: no sample line is CLAIM, because the sample has no `defect_category`.

### D-014 Filing windows: only a known, passed deadline blocks a claim
Status: accepted (2026-09-25, approved by the human lead). The deadline is the posted date plus the sourced window in `config/rules/amazon_us.yaml`.
- Known and passed: `within_filing_window` = FAIL. The decision is DO_NOT_CLAIM with `reason_code` `FILING_WINDOW_EXPIRED` (`R_FILING_WINDOW_PASSED`); the evidence checks and citations still show what the evidence says (D-015a).
- Unknown (no sourced value): UNCERTAIN. CLAIM is still allowed, but the reason, the check detail and `warnings` carry "filing deadline not verified". Evidence support and fileability are separate questions.
- Rule values are pasted by a human (`retrieved_by: human`) with a verbatim excerpt; the loader refuses a value without source URL, date and excerpt. Third-party guides go under `secondary_sources` as notes and never supply a value. All values were null on Day 2 (this environment cannot reach Amazon's pages); D-017 adds the first two, pasted by the human lead.
- Assumption to revisit when the text is pasted: the window runs from the line's posted date. If a published rule anchors elsewhere (e.g. shipment closed date), the anchor must be added to the rule entry.

### D-015 Engine choices made on Day 2 (not channel rules)
Status: accepted (2026-09-25). All in `config/engine.yaml` or `backend/app/engine/`; none claims to be what the channel publishes.
- Rule order is fixed and documented in `app/engine/__init__.py`; the first matching rule fires. Each rule names the check it rests on; the decision's confidence is that check's confidence.
- Confidence is deterministic: 1.00 for a verdict from exact comparison or Decimal/date arithmetic on ingested data; 0.90 for a verdict read from a human operator's recorded check; multiplied by unit coverage on CONTRADICTED. Documented in ARCHITECTURE.md.
- Custody windows: prep evidence must be captured before the posting date (at most 120 days before) on the same FBA shipment; returns evidence for a refund line must match the order and fall within 60 days before to 120 days after posting (widened from 60 after by D-019); a return of a "lost inbound" unit counts within 180 days after posting. Receiving is not relevant to any current charge type: a supplier shortfall is not a channel loss.
- Unit coverage: one unit-level record covers one unit. A line with quantity 2 and one unit record has coverage 0.5 and goes to REVIEW (`R_PARTIAL_COVERAGE`).
- Duplicates: same org, report type, charge type, unit, sku, shipment, order, quantity, amount and currency, posted within 30 days; non-zero fee lines only. The earliest is canonical and is cited by content hash.
- Already reimbursed (heuristic, revised after the rules review found two rule-9 breaches): a `reimbursement_report` line on a fee charge type can offset a fee with the same unit, charge type and currency posted on or before it, when shipment and order agree wherever both lines carry them. A refund offsets at most its own amount and at most what is left of a fee. Within one duplicate group it goes to the duplicates first (latest first), so a refunded duplicate is not claimed again. If a refund could belong to more than one fee otherwise, nothing is allocated and every candidate fee is REVIEW (`R_REIMBURSEMENT_AMBIGUOUS`). A loss-event reimbursement never offsets a fee. None matched in the sample. The validator checks that `amount_reimbursed` is no more than the cited refund lines add up to in the store.
- Loss-event evidence polarity (superseded by D-016): "contradicts" = against the channel's position (favours recovery). Lost inbound: a prep record on the shipment contradicts; a later customer return supports. Damaged in warehouse: a prep record with no failed check contradicts. Refund, item not returned: a returns record with identity PASS contradicts; identity FAIL supports.
- Citation validation failure: REVIEW, status pending, rule `R_CITATION_INVALID`, `reason_code` null. An exception while deciding one charge (or in the pre-checks, which then affects every charge): REVIEW, pending, rule `R_ENGINE_ERROR`, and the charge is still persisted (D-015c). Only `final` upstream records can settle a charge; `pending` and `overridden` ones count as uncertain.
- Decisions are append-only: each run inserts new rows with a new `run_id`; the app role has SELECT and INSERT only, and a CHECK constraint refuses a CLAIM row without a positive amount.
- Finding: FORCE RLS applies to the owner role too. An owner UPDATE without `app.current_org` set matches zero rows, so the test that edits stored evidence as the owner sets the org explicitly.

### D-015a Passed filing deadline is DO_NOT_CLAIM
Status: accepted (2026-09-25, human lead; replaces the Day 2 draft that made it REVIEW). When the sourced deadline is known and has passed, the decision is DO_NOT_CLAIM with the new `reason_code` `FILING_WINDOW_EXPIRED`, on both the evidence path and the duplicate path. The evidence checks, evidence status and citations are kept, so the record still shows the evidence supported recovery. An unverified deadline is unchanged (D-014).

### D-015b No defect category plus a failed prep check is DO_NOT_CLAIM
Status: accepted (2026-09-25, human lead). As in D-013.

### D-015c Separate reason codes for dependency and engine failures
Status: accepted (2026-09-25, human lead). New `reason_code` values: `DEPENDENCY_UNAVAILABLE` (database or other dependency failure, e.g. any SQLAlchemy error) and `ENGINE_ERROR` (any other exception while deciding). Both are persisted as REVIEW with status `pending`, rule `R_ENGINE_ERROR`. `MODEL_UNAVAILABLE` is reserved for the LLM layer. CLAUDE.md's vocabulary and rule 5 are updated to match.

### D-016 Loss events: evidence is scored against the line; decisions are mapped per charge type
Status: accepted (2026-09-25, human lead). Context: D-015 scored loss-event evidence by whether it favoured recovery, so the claim direction was inverted: a returned item counted towards claiming a non-return, and prep for a "lost" unit counted as contradicting the loss. Decision:
- `evidence_status` is always relative to what the line asserts. CONTRADICTED means "the evidence says the line is wrong" for every charge type. For a fee that favours recovery; for a loss event (lost, damaged, refunded and not returned) the line is what the seller would be reimbursed for, so CONTRADICTED makes the loss doubtful and SUPPORTED favours recovery.
- Loss events map to a decision through `config/engine.yaml` `loss_event_outcomes`, one commented row per outcome. None is ever CLAIM (D-011).
  - Refund, item not returned: the ordered item came back with identity, parts and condition all PASS: CONTRADICTED, DO_NOT_CLAIM (`R_ITEM_RETURNED`). Identity PASS but parts FAIL or not recorded, or condition FAIL, UNCERTAIN or not recorded: CONTRADICTED, REVIEW (`R_RETURNED_INCOMPLETE_OR_DAMAGED`, "possible separate claim"). A different item came back: SUPPORTED, REVIEW until an amount is computable. No returns record in the custody window: INSUFFICIENT, `NO_RELEVANT_EVIDENCE`; the reason notes the absence is consistent with the seller's claim but is not evidence.
  - Lost inbound: prep on the shipment and no later record of the unit: SUPPORTED, REVIEW until an amount is computable. A final customer return of the unit after the loss with identity PASS: CONTRADICTED, REVIEW (`R_LOSS_DOUBTFUL`), whatever prep shows. A later return with identity FAIL, UNCERTAIN or not recorded is not a sighting: INSUFFICIENT.
  - Damaged in warehouse: a final prep record with at least one check, every one PASS: SUPPORTED, REVIEW until an amount is computable. A FAIL or UNCERTAIN check, or no checks: INSUFFICIENT (tightened after the rules review: an all-UNCERTAIN record shows nothing).
  - Pending records, or a mix of uncertain and settled findings: INSUFFICIENT. Contradicting and supporting findings together (refund, damaged): CONFLICTING. Both REVIEW.
- A known passed deadline on a loss event is DO_NOT_CLAIM with `FILING_WINDOW_EXPIRED` (`R_FILING_WINDOW_PASSED`), checked after rules 7-9 (numbering after D-017) and before the evidence mapping, with the evidence checks kept. The reason says the deadline was computed from the posted date as a proxy for the event date.
- Next actions: only rows on the claim path (`amount_needed: true`) point to a unit value and an override with an amount. Rows where the evidence refutes the seller's claim tell the reviewer not to claim. The loader requires a next action on every REVIEW row and refuses one on a DO_NOT_CLAIM row. A test fails if a refuting row's next action mentions override, amount or claim other than "do not claim". The citation validator refuses any CLAIM on a loss event (defence in depth).
- Consequences: D-015's loss-event polarity bullet is replaced by this entry. CLAUDE.md's mapping applies to fee lines; loss events follow this table.

### D-017 Sourced filing windows with an open day
Status: accepted (2026-09-25, human lead). Context: the human lead pasted verbatim excerpts from an official Seller Central announcement (https://sellercentral.amazon.com/seller-forums/discussions/t/81c3235d-4c44-47ba-96c5-883cecab3244, posted by News_Amazon under News and Announcements, 2024, retrieved 2026-09-25 by a human). It says the FBA inventory reimbursement policy page would be updated, so it may be superseded; every entry carries that caveat. Decision:
- `config/rules/amazon_us.yaml` `filing_windows` entries carry `window_open_days` and `window_close_days` (both sourced or null), plus `anchor`, `source_type`, `assumption` and `caveat`.
- `damaged_in_warehouse`: closes 60 days after "the item was reported lost or damaged". `refund_issued_item_not_returned`: opens 60 and closes 120 days after "the customer refund or replacement date". Assumption on both: the report line's `posted_date` is used as a proxy for that date, since no upstream record carries it. Every reason built on a window says so.
- Removal claims (lost in transit: 15-75 days from shipment creation; all others: within 60 days of delivery back) are stored under `unmapped_rules` with `applies_to: null`. No sample charge type maps to them and the engine never reads them.
- Not filled from this source, because it does not cover them: `lost_inbound` (inbound shipments), `inbound_defect_fee`, `fulfilment_fee_weight_tier`. They stay null ("filing deadline not verified").
- Engine: before the window opens, `within_filing_window` = FAIL with detail "not yet eligible", decision REVIEW, `reason_code` `FILING_WINDOW_NOT_OPEN`, rule `R_FILING_WINDOW_NOT_OPEN`. It is rule 1, so a line whose window has not opened is never CLAIM or DO_NOT_CLAIM; the evidence checks are still computed and shown, and the next action names the date the window opens. Inside the window the evidence decides. After it closes: D-015a and D-016. An open day with no sourced close: "not yet eligible" before it, "filing deadline not verified" after.
- Consequences: on the sample (as of 2026-09-25), the damaged-in-warehouse line is past its deadline, and every refund line is inside its window.

### D-008 update: confirmed by the organisers (2026-09-25)
Nandhan Rao (Sydon) confirmed in the official participant group that no exact JSON schema or type definitions exist for subject, agent, images and outcome. Participants should proceed from the handbook field list and document assumptions. D-008 stands as the contract baseline; its assumptions are listed in README "Assumptions and limitations".

### D-018 Evidence is keyed by pod and record_id
Status: accepted (2026-09-25, review triage of docs/reviews/copilot-pr14.md, approved Day 3 plan). Context: a `record_id` is unique only within the pod that emits it, but evidence was unique on `(organization_id, record_id)` and looked up by `record_id` alone, so a prep record and a returns record with the same id would collide and a citation could resolve to the wrong one. Decision:
- `evidence_records` is unique on `(organization_id, agent, record_id)` (migration 0003). Every lookup takes the pod and the id (`repo.get_record`, `repo.get_record_with_hash`).
- An evidence citation carries `agent`; a charge citation does not (model validation). The validator looks the record up by pod and id and fails closed if the stored record's pod or id differ.
- Attachments store `agent`, and the attachment key's HMAC input includes it (D-010). Rows ingested before 0003 keep a null `agent`.
- The adapter refuses a duplicate `(org, agent, record_id)` within one load and keys raw sources by `(agent, record_id)`.
- Consequence: decision records now carry `agent` on evidence citations, so their content hashes differ from Day 2 runs of the same inputs. Decisions and rule counts do not change.

### D-019 Refund custody window runs to the filing window's close; unresolved units never show evidence present
Status: accepted (2026-09-25, Day 3 Task 1, approved by the human lead).
- Refund, item not returned: the returns custody window was 60 days either side of posting, narrower than the sourced 60-120 day filing window (D-017). A genuine return arriving between 61 and 120 days after posting was outside the window and read as "no return" (REVIEW, evidence outside window) while a claim could still be filed. The window after posting is now 120 days (`config/engine.yaml`). The window before posting stays 60 days.
- `check_windows_consistent` (`app/core/rules.py`, called by every run) refuses an engine config where a pod that reads evidence after posting stops before the charge type's sourced filing window closes, so the two cannot drift apart again.
- An unresolved unit (no record carries it, or an identity key conflicts) now gives `evidence_present` = UNCERTAIN and `evidence_in_custody_window` = UNCERTAIN, both with detail "unit not resolved: <reason>". Before, `evidence_present` showed PASS with the resolution failure as detail. The decision is unchanged (R_UNRESOLVED_UNIT, REVIEW).
- Effect on the sample: none. Every sample unit resolves, and every sample return was captured on its refund's posting day. The regression snapshot is unchanged.

### D-020 POST /agent: key-bound organisation, today's date, config checked first
Status: accepted (2026-09-25, Day 3 Task 4 and the rules-guardian review).
- The organisation comes only from the API key (`ALIBI_API_KEYS`, `org:sha256` pairs, compared with `hmac.compare_digest`). The endpoint has no organisation field. Another organisation's rows, malformed ones included, are skipped, never stored under the caller.
- Decisions are judged as of today (UTC). The caller cannot choose `as_of`: a past date would reopen an expired filing window, a future date would store DO_NOT_CLAIM `FILING_WINDOW_EXPIRED` for charges still fileable. Replays use the CLI.
- `check_windows_consistent` runs before anything is written, so a bad engine config refuses the request (500) instead of storing charges with no decision.
- Limitation: FastAPI parses the multipart body before the key check, so an unauthenticated upload is received (not stored) before its 401. A request-size limit in front of the app is deployment work (Day 5).
