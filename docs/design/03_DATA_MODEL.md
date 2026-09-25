# 03 Data Model

All models are Pydantic v2, frozen where they represent facts. Money is `Money(amount: Decimal, currency: str)`. Timestamps are timezone-aware UTC.

## Entities (the graph)

```
Supplier 1--* PurchaseOrder 1--* POLine (sku, qty, unit_cost)
Shipment (inbound to FC or outbound order shipment)
  1--* Carton 1--* CartonLine (sku, qty)
  *--* Order (for outbound)
Order 1--* OrderItem (sku, qty)
Unit (serial / LPN / FNSKU instance) -> sku, current shipment/order
Sku  (seller_sku, asin, fnsku, variant attributes, declared dims/weight)
```

```python
class Sku(BaseModel):
    seller_sku: str          # canonical, e.g. "SKU-9281"
    asin: str | None
    fnsku: str | None
    title: str
    variant: dict[str, str]  # size, colour
    unit_cost: Money | None  # from Receiving/PO, used for valuation

class Shipment(BaseModel):
    shipment_id: str         # "SHP-10291"
    direction: Literal["INBOUND_TO_FC", "OUTBOUND_ORDER", "RETURN", "REMOVAL"]
    created_at: datetime
    handed_over_at: datetime | None   # custody change to carrier/FC
    delivered_at: datetime | None
    carrier: str | None
    tracking: str | None
    destination: str | None           # FC code
    cartons: list[Carton]

class Carton(BaseModel):
    carton_id: str
    lines: list[CartonLine]           # sku, qty
    declared_weight_kg: Decimal | None

class Order(BaseModel):
    order_id: str
    items: list[OrderItem]
    shipment_ids: list[str]
    ordered_at: datetime

class Unit(BaseModel):
    unit_id: str                      # serial / LPN
    seller_sku: str
    shipment_id: str | None
    order_id: str | None
```

## Charges (fees and reimbursements, one model)

```python
class ChargeKind(StrEnum):
    FEE = "FEE"                       # money taken from seller
    REIMBURSEMENT = "REIMBURSEMENT"   # money paid to seller
    REVERSAL = "REVERSAL"             # reimbursement clawed back

class Charge(BaseModel):
    charge_id: str
    kind: ChargeKind
    reason_code: ReasonCode           # normalised enum, see 05_DECISION_ENGINE.md
    reason_raw: str                   # exactly as in source
    amount: Money                     # absolute value
    quantity: int | None              # units the charge covers
    posted_at: datetime
    event_at: datetime | None         # when the underlying event happened, if stated
    shipment_id: str | None
    order_id: str | None
    seller_sku: str | None
    asin: str | None
    fnsku: str | None
    case_id: str | None
    original_charge_id: str | None    # for reversals/adjustments
    source: SourceRef                 # file hash, row number or text span
    ingestion_warnings: list[str]

class SourceRef(BaseModel):
    file_id: str
    file_sha256: str
    locator: str                      # "row:17" or "page:2,chars:1044-1102"
    raw: dict[str, Any] | str         # untouched original row/text
```

## Evidence records (the contract with the other Managers)

Common envelope plus a typed body per Manager. This envelope is the thing to show judges: "any Manager that emits this shape plugs into Recovery".

```python
class EvidenceRecord(BaseModel):
    record_id: str                    # globally unique, e.g. "PRP-000123"
    manager: Literal["RECEIVING", "PREP", "PACK", "RETURNS"]
    captured_at: datetime
    captured_by: str | None           # operator or agent id
    refs: EntityRefs                  # shipment_ids, order_ids, skus, unit_ids, carton_ids, po_ids
    attachments: list[Attachment]     # photo/video refs with sha256, never parsed by us
    notes: str | None                 # free text, untrusted
    body: ReceivingBody | PrepBody | PackBody | ReturnsBody
    content_sha256: str               # hash of canonical JSON, used in claim packets
    source: SourceRef

class CheckResult(StrEnum):
    PASS = "PASS"; FAIL = "FAIL"; NOT_CHECKED = "NOT_CHECKED"; INCONCLUSIVE = "INCONCLUSIVE"

class ReceivingBody(BaseModel):
    po_id: str
    lines: list[ReceivedLine]         # sku, qty_expected, qty_received, qty_damaged, variant_match: bool
    unit_cost: dict[str, Money]       # sku -> cost

class PrepBody(BaseModel):
    unit_scope: UnitScope             # units or sku+qty this inspection covers
    packaging: CheckResult
    label: CheckResult
    barcode_scan: CheckResult
    barcode_value: str | None
    warning_labels: CheckResult
    polybag: CheckResult
    measured_dims_cm: tuple[Decimal, Decimal, Decimal] | None
    measured_weight_kg: Decimal | None

class PackBody(BaseModel):
    pack_context: Literal["CARTON", "ORDER"]
    carton_id: str | None
    order_id: str | None
    expected: list[SkuQty]
    observed: list[SkuQty]
    decision: Literal["SEAL", "STOP"]
    carton_weight_kg: Decimal | None

class ReturnsBody(BaseModel):
    order_id: str
    received_at: datetime | None      # None = expected but not received
    item_matches_order: CheckResult
    complete: CheckResult
    condition: Literal["NEW", "LIKE_NEW", "GOOD", "DAMAGED_CUSTOMER", "DAMAGED_CARRIER", "DEFECTIVE", "WRONG_ITEM", "UNKNOWN"]
    disposition: Literal["RESTOCK", "REFURBISH", "DISPOSE", "RETURN_TO_VENDOR", "CLAIM"]
```

## Reimbursement ledger (for ALREADY_REIMBURSED)

```python
class ReimbursementEntry(BaseModel):
    reimbursement_id: str
    case_id: str | None
    related_charge_id: str | None
    order_id: str | None
    shipment_id: str | None
    seller_sku: str | None
    reason_code: ReasonCode
    amount: Money
    quantity_cash: int
    quantity_inventory: int
    approved_at: datetime
    original_reimbursement_id: str | None
```

## Decision outputs

```python
class Polarity(StrEnum):
    CONTRADICTS = "CONTRADICTS"; SUPPORTS = "SUPPORTS"; NEUTRAL = "NEUTRAL"

class Strength(StrEnum):
    DIRECT = "DIRECT"        # checks exactly the asserted fact, inside custody window
    INDIRECT = "INDIRECT"    # related fact, or outside ideal window, or sibling scope

class Finding(BaseModel):
    finding_id: str
    charge_id: str
    record_id: str
    check: str                       # e.g. "PREP.packaging"
    polarity: Polarity
    strength: Strength
    covered_units: int | None
    rule_id: str                     # which rule produced it
    rationale: str                   # template text, no LLM
    notes_quote: str | None          # verbatim quote if notes were used

class Verdict(StrEnum):
    CONTRADICTED = "CONTRADICTED"; SUPPORTED = "SUPPORTED"; SILENT = "SILENT"
    UNCERTAIN = "UNCERTAIN"; DUPLICATE = "DUPLICATE"; ALREADY_REIMBURSED = "ALREADY_REIMBURSED"

class Decision(BaseModel):
    run_id: str
    charge_id: str
    verdict: Verdict
    coverage: Decimal                # 0..1 share of charged units contradicted
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    rule_path: list[str]             # ordered rule ids that fired
    findings: list[Finding]
    reason_code: str                 # machine reason for the verdict, e.g. "NO_RELEVANT_EVIDENCE"
    reason_text: str                 # human reason
    missing_evidence: list[str]      # what would have changed the verdict

class ClaimStatus(StrEnum):
    READY = "READY"; EXPIRED = "EXPIRED"; NEEDS_REVIEW = "NEEDS_REVIEW"

class Claim(BaseModel):
    claim_id: str
    run_id: str
    charge_id: str
    status: ClaimStatus
    claimable: Money
    unclaimed_remainder: Money
    remainder_reason: str | None
    computation: list[str]           # human-readable arithmetic steps
    citations: list[Citation]        # record_id + content_sha256 + field paths used
    explanation: str                 # LLM or template, validated
    filing_deadline: date | None
    case_text: str                   # draft text to paste into a marketplace case

class Citation(BaseModel):
    record_id: str
    content_sha256: str
    fields: list[str]                # e.g. ["body.packaging", "captured_at"]
```

## Audit

```python
class AuditEvent(BaseModel):
    event_id: str
    run_id: str
    charge_id: str | None
    stage: Literal["INGEST", "PRECHECK", "RESOLVE", "RETRIEVE", "FINDING", "AGGREGATE", "CLAIM", "VALIDATE", "LLM"]
    at: datetime
    payload: dict[str, Any]          # inputs/outputs of the stage, ids only for large objects
```

## Tables and indexes (Postgres)

- `files(id, sha256 unique, kind, uploaded_at, meta jsonb)`
- `charges(charge_id pk, run-independent, kind, reason_code, amount, currency, posted_at, event_at, shipment_id, order_id, seller_sku, ..., source jsonb)` index on (shipment_id), (order_id), (seller_sku), (posted_at)
- `evidence(record_id pk, manager, captured_at, refs jsonb, body jsonb, notes, content_sha256)` GIN index on `refs`; btree on captured_at
- `entity_*` tables for shipments, cartons, orders, units, skus with FK integrity
- `reimbursements(...)` index on related_charge_id, order_id, shipment_id+sku
- `runs(run_id, started_at, config jsonb, input_hashes jsonb, status)`
- `decisions(run_id, charge_id, verdict, ..., pk(run_id, charge_id))`
- `claims(claim_id, run_id, charge_id, ...)`
- `audit_events(event_id, run_id, charge_id, stage, at, payload jsonb)` append-only (revoke UPDATE/DELETE for app role)
