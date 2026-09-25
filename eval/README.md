# Held-out evaluation set

**Labellers:** you only need `LABELLING_GUIDE.md` and your own file (`labels_A.csv` or
`labels_B.csv`). You do not need to read the rest of this page, and nothing on it tells you
any answer.

## What is here

| Path | What it is |
|---|---|
| `data/fee_report_eval.csv` | 58 report lines (fee report, inventory adjustment, reimbursement report) on 52 units, both demo organisations |
| `data/upstream/{receiving,prep,pack,returns}_eval.csv` | the upstream records those lines can be checked against, in the same csv_v0 shape as `data/upstream/` |
| `LABELLING_GUIDE.md` | the human-written guide the labellers follow (not generated, not edited by the agent's author) |
| `labelling_sheet.csv` | one row per report line: `case_id`, the charge line, a plain-English evidence summary, and empty `label` and `reason` columns |
| `labels_A.csv`, `labels_B.csv` | each labeller's own copy of the sheet; they fill `label` and `reason` |
| `resolved_disagreements.csv` | after both have finished: the agreed label for every case they disagreed on, with a note |
| `make_sheet.py` | builds the sheet and the blank label files from the data |
| `run_eval.py`, `metrics.py` | the harness (see below) |
| `REPORT.md` | written by the harness; does not exist until labels are committed |

The set is **held out**: it was written on 2026-09-25, is separate from `data/` (no shared
unit, line, record, shipment or order id), and the agent has not been run on it. The
harness refuses to run the agent until both label files are committed to git.

All dates are judged **as of 2026-09-27** (`common.AS_OF`), both in the sheet's deadline
lines and when the harness runs the agent, so labellers and the agent see the same
deadline status. This is a fixed evaluation date (the day planned for the eval run), not
the date the set was written or the date the harness happens to run.

## How the cases were chosen

The cases were designed from the domain, starting from the five charge types and the
"things that change the answer" in section 6 of the labelling guide, not by reading the rule
engine and writing inputs that make it pass. For each charge type the question was: *what
situations does a recovery analyst actually meet, including the awkward ones?* That gives
the mix below. It is listed here by situation only. No expected answer was written down
anywhere, and the author of the agent did not label any case.

| Charge type | Lines | Situations covered |
|---|---|---|
| Inbound defect fee | 26 | a stated defect with the matching prep check recorded before shipping, across five different checks (plastic bag, suffocation warning, label, expiry date, handling marks); the matching check failed; the matching check uncertain; prep recorded after the fee was posted; prep for the unit on a different shipment; defect category blank with every check passed, and with one failed; quantity 2 with one unit's record; a sibling SKU on the prep record; a defect for something the work order did not require; a defect category prep does not check; two prep records that disagree; the same fee charged twice (two pairs, one with a stated category, one blank); a fee refunded in full, and one refunded in part, by a reimbursement line |
| Fulfilment fee (weight tier) | 7 | no measured weight on file; no record of the unit at all; the same fee charged twice for the same order (two pairs); a fee of $0.00 |
| Lost inbound | 6 | prep on the shipment and nothing afterwards; a customer return of the unit after the loss; only a receiving record showing a supplier short-shipment; prep on a different shipment; a loss Amazon has already paid for; no record of the unit at all |
| Damaged in warehouse | 6 | prep all passed, inside the known deadline; prep all passed, deadline passed; a failed prep check; only a receiving record; an uncertain prep check; a damage Amazon has already paid for |
| Refund issued, item not returned | 13 | returned complete; returned damaged; returned with a part missing; the wrong item came back; no return recorded; a genuine return that arrived 87 days after the refund; filing window not yet open; deadline passed; returns team unsure it was the right item; a return logged against a different order; two returns records that disagree; a returns record still pending; condition uncertain (signs of use) |

Both organisations appear in every charge type except lost inbound, where one organisation
has 4 lines and the other 2. Identifiers were numbered with a fixed random seed after the
cases were written, so a case's id, unit number and position in the file say nothing about
its situation. The one-off script that wrote the CSVs is not committed: its comments name
the situation of each case, and a labeller who read them would be biased.

Amounts, SKUs, orders and operators are synthetic, like `data/`. Deadlines come only from
the sourced rules in `config/rules/amazon_us.yaml` (D-017), counted from the posted date.

## Known limitation: who wrote the cases

The same person (the agent's author, working with an AI coding assistant) wrote the rule
engine and these cases, in the same session, and cannot unread the rules. The cases may
therefore lean towards situations the engine already handles. One concrete instance: the
case of a genuine return arriving 87 days after the refund was written minutes after the
fix it exercises (D-019, the returns custody window widened to 120 days). The protections
are:

1. Labels come only from two humans, labelling independently, who never see the agent's
   output. The agent's author does not label.
2. The agent is not run on this set until both label files are committed. The harness
   checks this with git.
3. The human lead reviews the sheet before labelling, and can add, change or remove cases
   first.
4. Disagreements between the labellers are reported (raw agreement and Cohen's kappa
   before resolution), not hidden.

## How the evidence summaries were written

`make_sheet.py` builds each summary from the ingested records through the same csv_v0
adapter the agent uses, so both see the same records and the same PASS / FAIL / UNCERTAIN
mapping (`config/adapters/csv_v0.yaml`). Every verdict is followed by the value the team
actually recorded (e.g. "Amazon label placement UNCERTAIN (recorded: on curve)", "original
barcode covered PASS (recorded: yes)"), so a labeller can disagree with the mapping instead
of inheriting it. Deadline lines say that the posted date is used in place of the event
date. This is the same assumption the agent makes (D-017), stated so a labeller can weigh it. Summaries use only the
guide's terms: PASS, FAIL, UNCERTAIN; Receiving, Prep, Pack, Returns; the five charge type
names. Every summary ends with the deadline status: no known deadline, inside the known
window, window not yet open, or known deadline passed.

The script imports nothing from the decision path (engine, pre-checks, resolution,
retrieval, pipeline, claims), and a test enforces this. It states facts only: it never says
"duplicate", "already reimbursed" or anything else that names an outcome. Other report lines
for the same unit are listed so a labeller can judge that for themselves.

## Workflow

1. `cd backend && uv run python ../eval/make_sheet.py --templates` (already done; refuses
   to overwrite a label file that has labels).
2. The human lead reviews `labelling_sheet.csv`.
3. Labeller A fills `labels_A.csv`, labeller B fills `labels_B.csv`, independently. Both are
   committed to git.
4. `make eval`: prints raw agreement and Cohen's kappa, lists the disagreements, and stops.
5. The two labellers (or the human lead) resolve each disagreement in
   `resolved_disagreements.csv` (`case_id,gold_label,note`) and commit it.
6. `make eval` again: runs the agent on the set as of 2026-09-27 and writes `REPORT.md`.

## The harness

`run_eval.py` refuses to run unless `labels_A.csv` and `labels_B.csv` exist, are tracked by
git and have no uncommitted changes, and every case has a label from the vocabulary. The
eval data and `labelling_sheet.csv` must be committed too, and the sheet and both label
files must still match, row for row, what `make_sheet.py` builds from the data now. So the
agent can never be scored on inputs the labellers did not see. It then:

- computes raw agreement and Cohen's kappa between A and B, before any resolution;
- builds gold labels: the shared label where A and B agree, otherwise the committed row in
  `resolved_disagreements.csv`. While any disagreement is unresolved it computes no agent
  metrics, lists those cases, and stops;
- runs the agent through the real pipeline (csv_v0 ingest, pre-checks, engine, citation
  validator, Postgres with row-level security) on a freshly migrated eval database. No
  mocks, and nothing from `data/`;
- reports charges evaluated, claims recommended, correct claims, false claims, missed
  claims, claim precision, REVIEW rate, all of these per charge type, latency per charge,
  cost (the number of model calls; 0 while `LLM_ENABLED=false`), and a table of
  case -> A -> B -> gold -> agent -> agree/disagree -> notes.

Exit codes: 0 done; 2 refused; 3 disagreements unresolved (agreement written, no agent
metrics); 4 report written, but the agent made at least one false claim (the PRD's hard
gate of 0 false claims); 5 a charge got no decision.

Definitions: a *correct claim* is agent CLAIM where gold is CLAIM. A *false claim* is agent
CLAIM where gold is not CLAIM. A *missed claim* is gold CLAIM where the agent did not say
CLAIM. *Claim precision* = correct claims / claims recommended, reported with N.
