# 01 Domain Primer

Enough domain knowledge to make the synthetic data and the rules realistic. Amazon FBA is the reference model because it is the most documented; the design generalises to Flipkart, Meesho, Shopify 3PLs, etc.

## Two kinds of money movement

**Fees (money taken from the seller)**
- Fulfilment (pick and pack) fees, based on size tier and weight. Wrong dimensions or weight means an overcharge.
- Storage and long-term storage fees.
- Inbound fees: placement fees, inbound defect fees for non-compliant shipments (labeling errors, missing prep, routing mistakes). As of 2026 Amazon consolidated several prep/label penalties into a per-unit inbound defect fee, and discontinued its own prep and labeling services for US sellers from January 1, 2026, so sellers must prep themselves or use a prep centre.
- Unplanned service fees: charged when items arrive without required label or prep and the FC has to do it.
- Returns processing fees, removal/disposal fees.
- Chargebacks (vendor side): no-show, carton label, ASN mismatches.

**Reimbursements (money returned to the seller)**
Typical reimbursement reasons: Damaged Inbound/Outbound, Damaged Warehouse, Lost Inbound/Outbound, Lost Warehouse, Customer Return (damaged or lost during return), and Reversal (Amazon claws back a reimbursement when inventory is found).

Common failure modes sellers audit for: partial reimbursements (paid less than the unit value), misclassified reimbursements, and claims closed without payment.

## Real report shapes (model our synthetic data on these)

**FBA Reimbursements report** (SP-API `GET_FBA_REIMBURSEMENTS_DATA`) columns include: approval-date, reimbursement-id, case-id, amazon-order-id, reason, sku, fnsku, asin, condition, currency-unit, amount-per-unit, amount-total, quantity-reimbursed-cash, quantity-reimbursed-inventory, quantity-reimbursed-total, original-reimbursement-id, original-reimbursement-type. The original-reimbursement fields let you trace reversals back to the original reimbursement event.

**Settlement report (flat file V2)**: settlement-id, settlement-start-date, settlement-end-date, deposit-date, total-amount, currency, transaction-type, order-id, merchant-order-id, adjustment-id, shipment-id, marketplace-name, amount-type, amount-description, amount, fulfillment-id, posted-date, order-item-code, sku, quantity-purchased. Fees appear as rows with `amount-type` = ItemFees / other-transaction and an `amount-description` such as FBAPerUnitFulfillmentFee.

**Finances API** (SP-API `listFinancialEvents`) groups events into lists such as ShipmentEventList, RefundEventList, ServiceFeeEventList, AdjustmentEventList, RemovalShipmentEventList. Good source of realistic field names. Verify exact names in the `amzn/selling-partner-api-models` GitHub repo before copying.

## Dispute windows (drive the EXPIRED logic)

Community-reported Amazon guidance: itemised FBA fee errors (fulfilment, returns, storage fees, usually weight/dimension issues) must be disputed within 90 days; non-itemised fees such as removal/disposal and prep and labeling fees follow an 18-month window. Vendor Central chargebacks must be disputed within 30 days. Treat these as configurable defaults in `config/dispute_windows.yaml`, not constants.

## What evidence wins disputes in the real world

- Dimension/weight disputes: measured dimensions and weight with timestamp and photo.
- Prep/label disputes: pre-shipment inspection record showing label, barcode scan result, polybag/bubble wrap present, photos.
- Inbound shortage: packing list and carton contents per box, carton weights, carrier proof of delivery with appointment ID.
- Lost/damaged: shipped quantity vs received quantity, condition at handoff.
- Returns: return received log, condition grade, whether the returned item matches the order item.

## How the five Managers map onto evidence

| Manager | Custody point | Evidence it produces | Can speak to |
|---|---|---|---|
| Receiving | Supplier -> seller warehouse | PO vs received qty, variant match, damage on arrival, unit cost | Unit cost (for valuation), condition before prep, supplier-side shortages |
| Prep | Seller warehouse, before shipment to FC | Per-unit packaging/label/barcode/warning compliance, dims/weight, photos | Prep and label defect fees, dimension/weight overcharges |
| Pack | Carton/order sealed | Expected vs actual contents per carton/order, seal decision, carton weight | Inbound shortage, wrong/missing item charges, lost inbound |
| Returns | Customer -> seller | Item identity, completeness, condition grade, disposition | Return-related fees, reversals, customer-return reimbursements |
| Recovery | After the fact | Verdicts and claims | Nothing new: it only reasons over the others |

The key insight for judges: Recovery Manager is the consumer of every other Manager's output. We define a clean evidence contract so any Manager can plug in.
