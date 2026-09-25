# One-pager: Alibi, the Recovery Manager

**Every charge deserves an alibi.**

## Customer
A small-to-mid Amazon seller (tens of SKUs, mostly FBA, some merchant-fulfilled through a 3PL) who is charged fees they believe are wrong and is owed reimbursements they never claim, because contesting requires evidence they don't have in one place.

## Problem
Charges post weeks after the event (inbound defect fees about six weeks after prep, per the sample data). The evidence lives in four separate places: receiving, prep, pack and returns. Today recovery is done by hand, by agencies taking a percentage, or not at all.

## What Alibi does
1. Ingests fee, inventory-adjustment and reimbursement report lines.
2. Matches each line to upstream evidence on `unit_id`, `fba_shipment_id` and `order_id`.
3. Returns one verdict per line: CONTRADICTED, SUPPORTED, SILENT or UNCERTAIN, plus DUPLICATE and ALREADY_REIMBURSED.
4. For contradicted lines, assembles a claim: amount with arithmetic, cited records with content hashes, and the rule that fired.
5. For everything else, states what it cannot claim and which missing record would change that.

## What it is not
Not a vision agent. Not an auto-filer. Not a model deciding verdicts from memory. Fee rules come from the channel's published documentation, retrieved and cited.

## Metrics

Targets are set before we have a baseline. We will report where we land against each one, and revise targets only with a written reason in the build log.

| Metric | How measured | Target |
|---|---|---|
| **Claim precision** (headline) | Of the charges Alibi marks as claimable, the share both labellers agree are valid claims, on 50 held-out charges | 95% or higher. Kill below 90% (K1) |
| False positives / false negatives | Counted separately, per charge type, with the failure mode behind each | Reported. Every false positive gets a named cause |
| Claim recall | Of the charges both labellers agree are claimable **from the available evidence**, the share Alibi finds | No target until the first baseline. Reported, not optimised at the cost of precision |
| Labeller agreement | Two people label each charge independently; raw agreement and Cohen's kappa, measured before Alibi is scored | 80% raw agreement and kappa of 0.6 or higher. Kill below (K3) |
| SILENT rate | Share of charges with no usable upstream evidence, by charge type | Reported. Drives what we ask the other pods to capture |
| UNCERTAIN rate | Share of charges with conflicting or ambiguous evidence | Reported. Never forced into a verdict |
| Isolation | A second organisation reads zero rows and cannot fetch another organisation's records by guessing a key | Pass / fail, tested |
| Fail-open | A model error or timeout still produces a record marked `pending` | Pass / fail, tested |

Why precision leads: a wrongly filed claim costs the seller standing with the channel; a missed one costs only money. Recall is measured only against claims the evidence could support, because a charge with no evidence upstream is a data gap, not an agent miss.

## Kill conditions

**K1: Precision.** If claim precision on the held-out set is below 90% after two rounds of fixes, Alibi stops drafting claims and ships only as an evidence-lookup tool. Wrong claims damage the seller more than no claims.

**K2: Evidence coverage.** If more than 60% of charge lines are SILENT because upstream records lack the fields needed (for example weight and dimensions for weight-tier fees), and the other pods can't add them by day 10, the product can't recover meaningful money yet. Stop and report which fields the chain must capture.

**K3: Task definition.** If the two human labellers agree on fewer than 80% of charges (or kappa is below 0.6), the verdicts are not well-defined. Stop building and redefine them before measuring anything else.

**K2 is at risk on the sample data, today.** 42 of the 61 sample lines (69%) are weight-tier fulfilment fees, and no upstream record in the sample captures weight or dimensions. If that holds, those lines are all SILENT and K2 trips before we write a line of code. We are not lowering the threshold. The fix is upstream: our contract proposal asks the Prep pod to record measured weight and dimensions per unit. If the shared catalogue holds declared weights, those can at most make a line UNCERTAIN, never CONTRADICTED, because a declared weight is not a measurement.

Sample line mix: 42 weight-tier fees, 9 inbound defect fees, 5 lost inbound, 4 refunds with item not returned, 1 damaged in warehouse.

## Dependencies and risks
- Four other pods must hold an agreed evidence-record shape (contract proposed in week one).
- "Unit" is defined differently across the sample files (PO line vs single unit). Raised as a finding.
- Weight-tier fees have no upstream evidence in the sample shape. Requested in the contract.
- Real fee schedules and dispute windows must be retrieved from the channel's documentation, not the sample amounts.
