# 05 Decision Engine

The engine is pure Python functions over typed models. No I/O, no LLM calls inside rules (free-text note classification happens before, in the findings stage, and arrives as a validated enum).

## Reason taxonomy

`ReasonCode` enum with a synonym map in `config/reason_synonyms.yaml`. Unknown text goes to the LLM normaliser (constrained to the enum or `UNKNOWN`). `UNKNOWN` charges are decided SILENT with reason `UNMAPPED_REASON`.

| ReasonCode | Kind | Platform assertion | Relevant Managers (primary, secondary) | Checks that bear on it |
|---|---|---|---|---|
| PREP_PACKAGING_DEFECT | FEE | Units arrived with missing/improper packaging | PREP; PACK | PREP.packaging, PREP.polybag |
| LABEL_DEFECT | FEE | Units arrived without valid label/barcode | PREP | PREP.label, PREP.barcode_scan (value must equal FNSKU) |
| WARNING_LABEL_MISSING | FEE | Required warning/suffocation label missing | PREP | PREP.warning_labels |
| INBOUND_QTY_SHORTAGE | FEE | Fewer units than declared (box content discrepancy) | PACK; PREP | PACK.observed vs declared qty |
| INBOUND_DEFECT_OTHER | FEE | Generic inbound defect | PREP; PACK | Any relevant check; defaults to UNCERTAIN unless a specific check applies |
| FULFILLMENT_FEE_SIZE_TIER | FEE | Unit falls in size tier T | PREP | PREP.measured_dims_cm, measured_weight_kg -> computed tier |
| WRONG_ITEM_SHIPPED | FEE | Customer received wrong/missing item | PACK; RETURNS | PACK.observed vs order; RETURNS.item_matches_order |
| RETURN_DAMAGED_BY_SELLER | FEE | Returned item defective due to seller | RETURNS; PACK | RETURNS.condition |
| LOST_INBOUND | REIMBURSEMENT | N units lost in inbound, reimbursed M | PACK | PACK.observed qty vs FC received qty vs reimbursed qty |
| DAMAGED_INBOUND | REIMBURSEMENT | Units damaged inbound, reimbursed M | PREP; PACK | Condition at handover |
| CUSTOMER_RETURN_NOT_RECEIVED | REIMBURSEMENT | Refunded but return not reimbursed | RETURNS | RETURNS.received_at is None past window |
| REIMBURSEMENT_REVERSAL | REVERSAL | Inventory found / item returned | RETURNS; RECEIVING | RETURNS.received_at, condition |
| UNKNOWN | any | n/a | none | SILENT |

This table lives in `config/relevance.yaml` so it is data, not code. Judges like seeing that.

## Custody windows (temporal rule)

For each reason, evidence is only DIRECT if captured inside the window where it can speak to the asserted fact:

- Prep/label/packaging assertions: `captured_at <= shipment.handed_over_at` and no later record for the same units shows a FAIL or damage. If captured more than `prep_staleness_days` (default 14) before handover, downgrade to INDIRECT.
- Pack contents: `captured_at <= handed_over_at` and the record's carton/order matches.
- Returns: `captured_at >= order delivery` and inside the return window.
- Records captured after the custody point can never CONTRADICT a pre-custody assertion. They can only produce NEUTRAL or, if they show a defect, SUPPORTS.

## Scope matching (the sibling-SKU trap)

A record bears on a charge only if its `refs` intersect the charge's resolved scope at the right granularity:

1. Unit-level charge (unit IDs known): record must reference those units, or reference the SKU + shipment with a unit_scope that covers them.
2. SKU-level charge on a shipment: record must reference that SKU and that shipment (or that SKU's cartons in the shipment).
3. Shipment-level charge with no SKU: record must reference the shipment; coverage is computed over units in the shipment.

Shipment match alone with a different SKU is never a match.

## Findings (per record, per check)

```
finding(check, record, charge) ->
  result PASS on a check that directly tests the assertion, inside window, in scope  -> CONTRADICTS, DIRECT
  result FAIL on that check                                                          -> SUPPORTS, DIRECT
  NOT_CHECKED / INCONCLUSIVE                                                          -> NEUTRAL
  in scope but outside window, or related check only                                  -> polarity as above, INDIRECT
  free-text note classified as DEFECT_MENTIONED with verified quote                   -> SUPPORTS, INDIRECT
  free-text note classified as SUSPICIOUS_INSTRUCTION                                 -> NEUTRAL + flag
```

Numeric checks:
- Quantity: `observed_qty >= charged_shortfall_basis` contradicts a shortage; exact arithmetic, per carton, summed.
- Size tier: compute tier from measured dims/weight using `config/size_tiers.yaml`. If computed tier is lower than charged tier and the measurement is DIRECT, CONTRADICTS with partial amount = fee(charged tier) - fee(computed tier). Measurement noise margin (default 0.5 cm / 20 g) near a boundary produces UNCERTAIN, not a claim.

## Aggregation rules (ordered, first match wins)

| # | Rule id | Condition | Verdict |
|---|---|---|---|
| 0 | R_QUARANTINE | Charge failed ingestion validation | not decided, listed as quarantined |
| 1 | R_DUP | Duplicate fingerprint of an earlier charge in this or a prior run | DUPLICATE |
| 2 | R_UNMAPPED | reason_code UNKNOWN | SILENT (UNMAPPED_REASON) |
| 3 | R_UNRESOLVED | Entity resolution failed | SILENT (UNRESOLVED_ENTITY, names missing link) |
| 4 | R_NO_EVIDENCE | No records in scope from relevant Managers | SILENT (NO_RELEVANT_EVIDENCE) |
| 5 | R_CONFLICT_DIRECT | At least one DIRECT CONTRADICTS and at least one DIRECT SUPPORTS on overlapping units | UNCERTAIN (CONFLICTING_EVIDENCE) |
| 6 | R_SUPPORTED | DIRECT SUPPORTS covers all charged units, no DIRECT CONTRADICTS | SUPPORTED |
| 7 | R_CONTRA_FULL | DIRECT CONTRADICTS covers all charged units, no SUPPORTS of any strength on those units | CONTRADICTED, coverage 1 |
| 8 | R_CONTRA_PARTIAL | DIRECT CONTRADICTS covers k of n units, remaining units have no SUPPORTS | CONTRADICTED, coverage k/n |
| 9 | R_INDIRECT_ONLY | Only INDIRECT findings | UNCERTAIN (INDIRECT_EVIDENCE_ONLY) |
| 10 | R_NEUTRAL_ONLY | Only NEUTRAL findings | SILENT (EVIDENCE_DOES_NOT_ADDRESS_CHARGE) |
| 11 | R_DEFAULT | Anything else | UNCERTAIN (UNCLASSIFIED) |

After the verdict: **R_REIMBURSED** checks the reimbursement ledger. If reimbursed amount >= claimable, verdict becomes ALREADY_REIMBURSED. If partial, verdict stays CONTRADICTED and claimable is reduced.

Every Decision records `rule_path` (e.g. `["R_CONTRA_PARTIAL","R_REIMBURSED"]`) and `missing_evidence` (e.g. `["PREP inspection for units U-7..U-10 before 2026-08-02T10:00Z"]`). The missing-evidence list is generated from the scope minus covered units. It is one of the most useful outputs for the seller and a great demo moment.

## Duplicate fingerprint

`fp = (kind, reason_code, shipment_id or order_id, seller_sku, amount, quantity)`; duplicates if same fp and `abs(posted_at delta) <= dup_window_days` (default 10) and different charge_id, and no `original_charge_id` linking them as a legitimate adjustment. The earliest is canonical. Exact same charge_id appearing twice in files is an ingestion dedupe, not a DUPLICATE verdict.

## Amount calculation

```
per_unit = charge.amount / charge.quantity           (Decimal, if quantity known)
contradicted_value = per_unit * contradicted_units   (or fee difference for size tier)
claimable = min(contradicted_value, charge.amount) - already_reimbursed_for_this_charge
claimable = max(claimable, 0), quantise 0.01 HALF_UP
remainder = charge.amount - claimable - already_reimbursed
```

For reimbursement rows (under-reimbursement): `claimable = (units_owed - units_reimbursed) * unit_value`, where unit_value comes from the platform's own amount-per-unit when present, else Receiving unit cost, and the source of the value is cited. If no value source exists, the claim is NEEDS_REVIEW with amount computed on units only.

Every step is written to `claim.computation` as text: `"38.00 USD / 10 units = 3.80 per unit"`, `"6 units contradicted x 3.80 = 22.80"`.

## Confidence (derived, never from the LLM)

- HIGH: R_CONTRA_FULL or R_SUPPORTED with unit-level scope and all evidence inside window.
- MEDIUM: SKU-level scope, or R_CONTRA_PARTIAL, or any note classification involved.
- LOW: anything UNCERTAIN.

## Filing windows

`config/dispute_windows.yaml` maps reason_code to window days. `filing_deadline = posted_at + window`. If `run_date > filing_deadline`, claim status EXPIRED (still shown, with deadline). Within 14 days of deadline: flag URGENT in the UI.
