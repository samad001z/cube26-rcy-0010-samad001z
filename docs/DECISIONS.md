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

### D-021 Overrides live in their own append-only table; the engine's decision row is never changed
Status: approved by human lead 2026-09-27 (proposed 2026-09-26, Day 4; revised 2026-09-27 after the rules-guardian and test-guardian reviews).
- **Storage.** `decision_overrides` (migration 0004): one row per override, `SELECT, INSERT` only for the app role (a test pins the exact grant set on every table), RLS enabled and forced, foreign key `(organization_id, decision_record_id)` to `decisions`, so an override can only point at a stored decision of the same organisation. Database checks: the new decision differs from the one it replaces; a CLAIM carries a positive amount and nothing else does; reason and reviewer are not blank (any whitespace counts as blank); `(org, decision, sequence)` is unique.
- **Effective decision.** The newest override by sequence, or the engine's decision when there is none. The effective record is the engine record with `overrides` filled, `status: overridden`, `outcome.decided_by: human:<reviewer>` and the new decision; rule id, reason, checks and citations stay the engine's. It gets its own content hash; the engine record's hash still verifies.
- **History check.** Each override stores the engine record's hash and the previous override's hash. `check_chain` verifies every hash and link, that each override's original decision is the one it replaced, and that a CLAIM override's amount equals the engine record's charged minus reimbursed (so a row rewritten with a recomputed, unkeyed hash is still caught). The row's indexed columns are compared with its body. This runs on `GET /decisions` (per item), on `GET /decisions/{id}` and its line history, and before every new override. Any problem is returned as `integrity_problems` and refuses new overrides (409).
- **Only the newest decision of a line can be overridden** (409 otherwise). Older runs are history; their reimbursement figures may be out of date.
- **A human CLAIM** claims the charge not yet reimbursed (`amount_charged - amount_reimbursed`, from the engine's pre-check). No partial or typed amounts in Round 2. It is refused (409) when:
  - the record is pending (fail-open): reimbursements were never computed;
  - the charge type is a loss event: its amount is what the channel already paid, and what is owed needs an authoritative unit value (D-011, D-016);
  - the line is a fee refund (a reimbursement-report line on a fee type);
  - `within_filing_window` is FAIL: the sourced deadline passed, or the window is not yet open (D-014, D-015a, D-017);
  - `not_already_reimbursed` is not PASS: fully reimbursed, or a refund that could belong to more than one fee (`R_REIMBURSEMENT_AMBIGUOUS`), which would otherwise let two fees each claim the same refund;
  - the amount owed is not the charge itself: the charge type's `claim_basis` is not `full_amount` (a weight-tier fee is owed only the difference to the correct fee), or `amount_computable` is not PASS (amendment A1);
  - the store has changed since the run: refund lines are re-matched over every stored charge (as the pre-checks do) and the CLAIM is refused if the reimbursed amount differs from the decision's or a refund could now belong to more than one fee; and the filing window is judged on the day of the override, not the run's as-of date (amendment A2);
  - evidence covers only part of the charge (`coverage` below 1): an override cannot claim part of a charge (amendment A3);
  - nothing remains to claim.
  The would-be effective record then goes through the citation validator (`app/claims/validator.py`), re-reading the charge and cited refund lines from the store, with one check left out: "cites contradicting evidence or a canonical charge". The reviewer's stored reason stands in for it. Any validator error refuses the override. `GET /decisions/{id}` returns `claim_refusal` so the UI does not offer CLAIM when it would be refused.
- **Audit.** Every override writes a `DECISION_OVERRIDDEN` audit event in the same transaction, carrying record, line, sequence, original and new decision, reviewer, reason, claim amount, its content hash and the previous override's hash.
- **Concurrency.** Overrides are serialised per decision with a transaction-scoped advisory lock; the unique sequence is the database backstop.
- **Re-runs.** Overrides attach to one decision in one run. A re-run makes new decisions without overrides. So the earlier human judgement is never hidden, `GET /decisions` returns `earlier_override` (decision, reviewer, time, reason) on any line whose newest override sits on an earlier run, and the detail endpoint lists earlier decisions of the line (`line_history`).
- **Limitations.** The API key identifies an organisation, not a person: the reviewer name is recorded as the caller gives it. `GET /runs` counts are the engine's decisions, not the effective ones; the decisions list computes effective counts.
- **Amendment 2026-09-27, after the second and third rules-guardian reviews (stricter only). Approved by human lead 2026-09-27 (A1 amount basis, A2 store and date re-check, A3 partial coverage).** A1, A2 and A3 (third review) above add refusals; nothing that was refused is now allowed. When the run found the window not yet open but it is open today, the refusal says so and asks for a re-run. Also: `GET /decisions/{id}` judges the deadline today from the sourced rules and keeps the run's own check beside it (`deadline.at_decision`), and returns the same `claim_refusal` the POST would apply; `earlier_override` only reports an override on an older run; an override is re-checked against the newest decision of its line after it is inserted, so a run committed before that re-check rolls the override back (a run committing after it, before the override commits, is not caught: `run_org` takes no lock; the override then shows on the new run as `earlier_override`); the column check also covers `line_id` and `decision_record_id`. Two engine next actions that pointed to overrides the flow cannot do (`R_PARTIAL_COVERAGE` "claim the covered part by override", now "an override cannot claim part of a charge"; `R_REIMBURSEMENT_AMBIGUOUS` "decide by override", now "an override can only close the line as do not claim") are reworded like `NEXT_UNIT_VALUE`; decisions and sample counts are unchanged.
- **Resolved with approval (2026-09-27).** The engine's next action on loss-event rows that need a unit value (`NEXT_UNIT_VALUE`, `app/engine/__init__.py:70`) said "record an override with the amount", which this flow cannot do. It now reads: "Find an authoritative unit value for this unit and file the claim outside Alibi; loss-event claims cannot be made through an override in this version (D-021)." Decisions, rule ids and sample counts are unchanged; the content hashes of the affected decision records change. D-016's "point to a unit value and an override with an amount" is superseded on this point.

### D-022 Model explanations: Gemini on Vertex AI, written only from the trace, never in the decision path
Status: approved by human lead 2026-09-27 (provider, fallback rule and UI labels); built on `day5`.
- **What the model does.** It writes a 2-4 sentence plain-English explanation of a decision that the rule engine has already made, from that decision's trace (`app/llm/trace.py`). It never sets or changes a decision, an amount or a citation (rule 2). Notes classification is not built.
- **Provider.** Google Gemini on Vertex AI through the `google-genai` SDK with `vertexai=True`, behind a provider interface (`app/llm/client.py`) so another provider could be added. Only `vertex` is implemented; `anthropic` and `bedrock` are refused as not implemented. Every setting comes from the environment: `LLM_PROVIDER`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `LLM_MODEL` (no model name in code). Credentials: the Cloud Run service identity in production; locally, Application Default Credentials or a key file outside the repository (`GOOGLE_APPLICATION_CREDENTIALS`; a path inside the repository is refused).
- **One call per decision.** No retries (SDK retry attempts = 1), a timeout (`LLM_TIMEOUT_S`), temperature 0, JSON output with one field. Pending (fail-open) records are never sent.
- **Validation (rule 3).** The text is used only if every ID-like token, snake_case name, ISO date and number in it appears in the trace; it writes no date in another form; the only decision word in capitals is the record's own; it contains no link and no forbidden phrase. Limitation: this checks facts that can be checked mechanically. The wording between them is not checked for meaning, so a sentence can still be wrong without naming a wrong ID or number.
- **Fallback (clarifies rule 5).** Any failure (not configured, call error, timeout, empty answer, rejected text, unexpected error in the step) keeps the decision exactly as the engine made it and stores the standard template explanation with `fallback_reason`. `MODEL_UNAVAILABLE` (REVIEW, pending) stays reserved for model steps that feed a decision; the explanation step does not.
- **Recorded on the decision.** `explanation` {text, source `model`|`template`, prompt version, trace hash, model id, cached, latency ms, input and output tokens (output includes thinking tokens), cost estimate in USD, cost note, fallback reason}; `model_version` = the model id when the model's text is used. The cost is tokens times `LLM_PRICE_INPUT_USD_PER_MTOK` / `LLM_PRICE_OUTPUT_USD_PER_MTOK`, prices the operator copies from the Vertex AI pricing page; no price is in code, and the estimate is null when they are unset. A call whose text is rejected is still recorded (tokens and cost were spent).
- **Hashing.** The explanation is part of the record's content hash. An empty explanation is left out of the hash payload, so records stored before this change still verify.
- **Cache.** `llm_explanations` (migration 0005, forced RLS, SELECT/INSERT only) keyed by (organisation, trace hash). The trace hash covers the trace, the prompt version and the model; run-specific IDs are not in the trace, so a re-run of the same charge and evidence reuses the text without a call (recorded as cached, 0 tokens). A cached text is validated again before use.
- **Off by default.** `LLM_ENABLED=false`: no provider is built and every decision gets the template. Tests never reach the network: SDK responses are replayed from fixtures through a fake client, and every test blocks non-loopback sockets.
