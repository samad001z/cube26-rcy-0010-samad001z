# Demo data

A small, hand-written fee report and upstream files for showing Alibi. **Demo data only.** It is
not the sample data (`data/`), not the held-out eval set (`eval/`), and no result from it is
an evaluation result. Every identifier is in its own namespace (`DEMO-...`, `FBA-DEMO-01`,
`op_demo_*`), none is copied or derived from `data/` or `eval/`, and every row belongs to
`org_demo_alpha` (a `org_demo_bravo` run of these files decides nothing).

It was built so that one run shows all three outcomes:

| Line | Charge | What the files say | Decision (rule) |
|---|---|---|---|
| DEMO-F01-1 | inbound defect fee, category `polybag` | prep recorded the polybag present and sealed before shipping | CLAIM (R_CONTRADICTED_FULL) |
| DEMO-F02-1 | inbound defect fee, category `label` | prep recorded the label flat and the original barcode covered | CLAIM (R_CONTRADICTED_FULL) |
| DEMO-F04-1 | weight-tier fee | no upstream pod records weight or dimensions | REVIEW (R_NO_RELEVANT_EVIDENCE) |
| DEMO-F04-2 | the same weight-tier fee again, 12 days later | repeat of DEMO-F04-1 | CLAIM (R_DUPLICATE) |
| DEMO-F05-1 | inbound defect fee, category `handling_marks` | prep recorded handling marks missing | DO NOT CLAIM (R_SUPPORTED) |
| DEMO-F06-1 | inbound defect fee, category `expiry_date` | refunded in full by DEMO-F06-2 | DO NOT CLAIM (R_ALREADY_REIMBURSED) |
| DEMO-F06-2 | reimbursement line for DEMO-F06-1 | money back, not a charge | DO NOT CLAIM (R_FEE_REFUND_LINE) |
| DEMO-F07-1 | inbound defect fee, no category | prep checks all passed, but the line does not say which defect | REVIEW (R_DEFECT_CATEGORY_MISSING) |
| DEMO-F08-1 | lost inbound | the unit was returned by a customer after the loss | REVIEW (R_LOSS_DOUBTFUL) |
| DEMO-F09-1 | inbound defect fee, category `polybag` | the only prep record is 158 days before the fee, outside the 120-day window | REVIEW (R_EVIDENCE_OUTSIDE_WINDOW) |

None of these outcomes depends on the day the demo is run: the charge types used have no
sourced filing window yet (the deadline shows as "not verified"), and the dates inside the
files are fixed. The amounts are made up.

## Run it

```bash
make demo                      # CLI: decide the demo report for org_demo_alpha, then demo/check.sh
```

or, in the review UI, sign in as `org_demo_alpha` and choose **Run a report → Load demo data**.

`demo/check.sh` compares the run with the table above and exits 1 on any difference, so a
change in the engine that moves a demo line shows up here. It is a check on the demo, not a
test of the engine and not an accuracy measure.
