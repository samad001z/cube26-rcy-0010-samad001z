# 00 Problem Analysis

## The brief in one sentence

Given charges levied on a seller, find the ones that the seller's own operational evidence proves wrong, package those as defensible claims, and refuse everything else with a clear reason.

## What the judges score (from the brief) and how we answer each

| Evaluation focus | What most teams will do | What we do |
|---|---|---|
| Document/data parsing | LLM reads a CSV | Header-mapping adapters for CSV/XLSX/JSON, LLM only for PDF/free text, every extracted field carries a source reference and is verified against the source |
| Evidence retrieval | Vector search over evidence | Keyed retrieval over an entity graph plus time windows. Semantic search is how you get wrong-shipment matches |
| Cross-record matching | Match on one ID | Resolve charge -> shipment -> order -> SKU -> unit, and route to the Managers whose evidence is relevant to the charge reason |
| Structured reasoning | "The model thinks..." | Rule table with named rules; every verdict names the rule that fired |
| Claim correctness | Maximise claims | Minimise false claims. Amount capped by charge minus reimbursed, prorated for partial coverage |
| Evidence traceability | Paste evidence into text | Claims reference evidence by ID plus content hash; UI click-through to the source record |
| Conservative decision-making | Force a conclusion | UNCERTAIN and SILENT are first-class, visible, and explained |

## Gaps and ambiguities in the brief (and our resolution)

1. **Implicit join in the example.** The charge references `SHP-10291`; the evidence references `SKU-9281`. Nothing in the example links them. Resolution: we maintain an explicit entity graph (shipment contains SKUs and units). If a charge cannot be resolved to entities that the evidence also references, the verdict is SILENT with reason `UNRESOLVED_ENTITY`, naming the missing link.
2. **Inconsistent outcome labels.** The brief uses Contradicts/Supports/Silent and later introduces UNCERTAIN; duplicates and already-reimbursed are listed as scenarios but not as outcomes. Resolution: six verdicts, defined in `05_DECISION_ENGINE.md`: CONTRADICTED, SUPPORTED, SILENT, UNCERTAIN, DUPLICATE, ALREADY_REIMBURSED. CONTRADICTED carries a coverage ratio for partial evidence.
3. **Timing is never mentioned.** A packaging PASS only contradicts a packaging defect if the inspection happened before custody passed to the carrier/fulfilment centre and nothing was recorded after it. Resolution: temporal rules (evidence must fall inside the relevant custody window) are part of the engine.
4. **Reimbursements vs fees.** Fees are money taken from the seller; reimbursements are money returned. For fees, contradicting evidence means the fee was wrong. For reimbursement rows, evidence can show the seller was under-reimbursed (e.g. 10 units lost, 6 reimbursed). Resolution: both are modelled as a `Charge` with a platform `assertion`; the engine evaluates the assertion either way.
5. **Duplicate charges are claimable.** A second identical charge is itself a recoverable amount, and the evidence is the first charge record. We treat it that way, not as a discard.
6. **"Already reimbursed" can be partial.** We claim only the unreimbursed remainder.
7. **Dispute windows.** Real marketplaces enforce filing windows. A claim may be correct but no longer fileable. We mark it `EXPIRED` rather than silently dropping it.
8. **Data may not be provided.** The brief lists inputs but we should assume we need to generate a realistic synthetic dataset with ground truth. See `04_DATASETS.md`. If organisers provide data, it enters through adapters, so nothing downstream changes.

## Assumptions (write any new ones to DECISIONS.md)

- A1: Evidence records from other Managers are immutable once written and carry a capture timestamp and a record ID.
- A2: Every Manager record references at least one of: shipment ID, order ID, SKU/ASIN/FNSKU, unit serial/LPN.
- A3: Fee reports carry at minimum a charge ID, an amount, a currency, a date, and one entity reference. Anything missing is flagged at ingestion.
- A4: A "PASS" from a Manager covers only what that Manager checked (a Prep packaging PASS says nothing about quantity).
- A5: Amounts are in the report currency; no FX conversion inside a claim.

## The scenarios we must pass (from the brief)

1. Correct claim with full evidence
2. Claim with partial evidence
3. Claim with no evidence
4. Multiple charges on the same shipment
5. Fee matches evidence from a different Manager
6. Ambiguous evidence
7. Duplicate charges
8. Already reimbursed charges

Plus our own: evidence captured after the event, evidence for a sibling SKU in the same shipment, conflicting evidence across Managers, expired filing window, malformed report rows, prompt injection inside inspector notes. See `09_TEST_PLAN.md`.

## Why this track fits a production-grade bar

Its correctness is testable. A vision agent's accuracy depends on lighting and a camera; a recovery agent's accuracy depends on logic we control and can prove with a scorecard. This is also the Manager that turns the other four into money, so it is the one a company building this suite would care most about getting right.
