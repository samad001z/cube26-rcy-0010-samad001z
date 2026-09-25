# Evidence record contract: v0 proposal from Recovery (05)

**Status:** proposal, open for negotiation in week one. **Owner:** @samad001z (Recovery Manager).

Recovery is the only pod that reads all four of your records. This proposal asks for the smallest set of fields Recovery needs to contest or support a channel charge, and nothing more. Every field below maps to a charge type in the sample fee report.

## 1. Common envelope (every Manager, every record)

| Field | Type | Why Recovery needs it |
|---|---|---|
| `record_id` | string, unique per pod | Cited in every claim |
| `schema_version` | string, e.g. `v1` | So a shape change on day nine is detected, not silent |
| `org_id` | string | Tenancy isolation; Recovery never joins across orgs |
| `unit_id` | string | Join key across all five pods (see section 3) |
| `sku`, `fnsku`, `asin` | string | Secondary join keys and claim text |
| `fba_shipment_id` / `order_id` / `po_number` + `po_line` | string, where applicable | Charges reference these, not always `unit_id` |
| `captured_at` | ISO 8601, UTC | Recovery checks evidence was captured before custody changed |
| `operator_id` | string | Who made the judgment |
| `checks` | list of `{check_id, result, observed, required, rule_source}` | Recovery reads individual checks, not only the overall verdict |
| `verdict` | `pass` / `fail` / `uncertain` / `pending` | Overall outcome; `uncertain` and `pending` are first-class |
| `overrides` | list of `{original, new, reason, operator_id, at}` | An overridden verdict changes what Recovery can claim |
| `model_version` | string | Traceability in the claim |
| `photo_refs` | list of org-scoped, non-guessable keys | Attached to claims; never a shared guessable path |
| `content_sha256` | hex | Recovery cites the hash of the exact record it used |

`result` values: `pass`, `fail`, `uncertain`, `not_required`, `not_checked`. `rule_source` is the URL of the published channel rule the check was made against.

## 2. Pod-specific asks

**02 Prep (highest priority).**
- **`measured_weight_g` and `measured_dims_mm` (L x W x H) per unit.** 42 of the 61 sample fee lines are weight-tier fulfilment fees, and today no pod records weight. Without this, Recovery can never contest the most common charge.
- `handed_over_at`: when the shipment left prep, so Recovery knows which records fall before custody changed.
- Per-check results for label placement, barcode coverage, polybag and warnings (already largely present).

**01 Receiving.**
- `unit_cost_usd` per unit (from the PO), so reimbursement shortfalls can be valued. Keep supplier shortfalls clearly separate from channel losses.

**03 Pack.**
- Carton or order contents as structured `{sku, qty}` lists (already present) plus `carton_weight_g` at seal.

**04 Returns.**
- `received_at`, and whether the return came back to the seller or to the channel's warehouse. Recovery needs this to decide whether "refund issued, item not returned" is contradicted.

## 3. Open question: what is a unit?

In the sample, a Receiving record covers a purchase-order line (for example 48 units), while fee lines carry quantity 1 on the same `unit_id`. One `unit_id` in the sample is lost inbound, then charged a fulfilment fee, then returned. That can't be one physical unit.

**Proposal:** `unit_id` identifies one physical unit. Receiving records reference the lot through `po_number` + `po_line` and list the `unit_id`s they cover. If the pods prefer lot-level records, we need an explicit `lot_id` and a unit-to-lot mapping. Either works; ambiguity doesn't.

## 4. What Recovery publishes back (its own output)

A claim record per charge line: `line_id`, `verdict` (contradicted / supported / silent / uncertain / duplicate / already_reimbursed), `claim_amount_usd` with arithmetic, cited `record_id`s with their `content_sha256`, the rule that fired, `missing_evidence`, `overrides`, and `content_sha256` of the claim itself. Readable by any pod that wants to know which of its records mattered.

## 5. Change policy

- Additive changes: announce in the `contract` thread 24 hours ahead.
- Breaking changes (rename, remove, change meaning): only before day 7, agreed by every consuming pod.
- Every record carries `schema_version`, so consumers detect a change instead of discovering it.
