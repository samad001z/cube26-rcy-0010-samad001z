# Alibi: Product Requirements Document

**Every charge deserves an alibi.**

| | |
|---|---|
| Product | Alibi, the Recovery Manager for ecommerce operations |
| Track | CodeQuesters, Recovery Manager (#5 RCY) |
| Owner | Syed Saad Ur Rahman |
| Status | v1 scope for the Round 2 build, revised 2026-09-27 to match what is built (see ARCHITECTURE.md) |

## 1. Problem

Marketplaces charge sellers fees (packaging and label defects, inbound shortages, size-tier fulfilment fees) and issue reimbursements for lost or damaged stock. These arrive weeks after the event. By then the proof of what happened is scattered across four teams: Receiving, Prep, Pack and Returns.

Sellers either lose money they are owed, or file claims they cannot back up, which get rejected. Recovery today is manual spreadsheet work: slow, inconsistent, and impossible to audit.

## 2. Users

| User | Needs |
|---|---|
| **Recovery analyst** (primary) | Know which charges are wrong, have the evidence ready, file defensible claims before deadlines |
| **Ops manager** | See money recovered and money lost, and which process gaps cause the losses |
| **Other Managers' teams** (Receiving, Prep, Pack, Returns) | Know which records their evidence needs to contain so future charges are recoverable |

## 3. Goals

1. Decide, for every charge, whether the seller's own evidence **contradicts** or **supports** it, or is **insufficient** or **conflicting**, and route it to CLAIM, DO NOT CLAIM or REVIEW.
2. Produce claims that are **defensible**: every claim cites real records, with the amount arithmetic shown.
3. **Never invent evidence.** When evidence is missing or conflicting, say so explicitly and say what is missing.
4. Make every decision **traceable and reproducible**: same input, same output, full audit trail.

## 4. Non-goals (v1)

- No camera or vision workflow. This Manager works on structured records only.
- No automatic filing with marketplaces. Alibi prepares the case; a human files it.
- No LLM deciding verdicts or amounts. The AI parses, explains and orchestrates only.
- No model training or fine-tuning.

## 5. User stories

1. As an analyst, I upload a fee report, a reimbursement report and evidence files, and see which rows were rejected and why.
2. As an analyst, I see every charge with a decision (CLAIM, DO_NOT_CLAIM, REVIEW), an evidence status (CONTRADICTED, SUPPORTED, INSUFFICIENT, CONFLICTING) and a reason code (e.g. DUPLICATE_CHARGE, ALREADY_REIMBURSED).
3. As an analyst, I open a contradicted charge and see the evidence chain, the rule that decided it, the amount arithmetic, and ready-to-paste case text.
4. As an analyst, I open a REVIEW charge and see exactly which evidence is missing or conflicting.
5. As an analyst, I ask Alibi questions in plain language ("what is claimable on SHP-10291?") and get answers that cite record IDs.
6. As an ops manager, I see totals: charged, claimable, expired, and money at stake.
7. As a judge or auditor, I see measured claim precision, REVIEW rate and failure modes on a held-out set labelled by two humans.

## 6. Functional requirements (v1)

| # | Requirement | Priority |
|---|---|---|
| F1 | Ingest CSV fee, adjustment and reimbursement reports and upstream evidence CSVs (csv_v0 adapter into the evidence contract shape); quarantine invalid rows with reasons | Must |
| F2 | Detect duplicate charges (claimable) and already-reimbursed charges (full or partial) | Must |
| F3 | Resolve each charge to shipment, carton, order, SKU and unit; report the missing link when resolution fails | Must |
| F4 | Retrieve evidence by exact keys, only from relevant Managers, only inside the custody time window | Must |
| F5 | Rule engine returning a decision, evidence status and reason code, with coverage for partial evidence, named rule path, and missing-evidence list | Must |
| F6 | Claim packets: amount with arithmetic, cited record IDs with content hashes, explanation, case text, filing deadline | Must |
| F7 | Citation validator: no claim is saved unless every cited record exists, matches its hash, and is in scope | Must |
| F8 | `POST /agent` and the `alibi run` CLI over the same deterministic pipeline; "Ask Alibi" chat that cites record IDs is a stretch goal | Must (chat: Could) |
| F9 | Dashboard: charges table, charge detail with evidence timeline, run overview, scorecard | Must |
| F10 | Eval report on a held-out set labelled independently by two humans before the agent runs: Cohen's kappa, claim precision, false and missed claims, REVIEW rate, latency, cost | Must |
| F11 | Glass Box: live view of rule firings during a run (stretch, docs/ROUND2_PLAN.md) | Could |
| F12 | Claim packets carrying content hashes of the decision and every cited record, with a check that recomputes them | Could |
| F13 | Cross-Examination: an adversarial agent that can only downgrade claims to review | Could |
| F14 | Evidence Gap ROI: money lost per missing-evidence type and owning Manager | Could |

## 7. Non-functional requirements

- **Correctness:** money in Decimal; a claim never exceeds the charge minus amounts already reimbursed.
- **Determinism:** identical inputs produce identical verdicts.
- **Auditability:** every stage writes an audit event; any decision is reconstructable.
- **Safety:** evidence text is treated as data, never instructions; prompt-injection cases are tested.
- **Degraded mode:** the full pipeline works with the LLM switched off.
- **Deployability:** one-command local start; a live URL for judges.

## 8. Success metrics

| Metric | Target |
|---|---|
| False claim rate | **0%** (hard gate) |
| Claim precision on the held-out eval set | Measured and reported with N; no target is claimed before labelling |
| Missed claims | Measured and reported |
| Claim amount exactness | 100% |
| Citation precision | 100% |
| Time from upload to a claim's evidence chain in the UI | Under 60 seconds |

## 9. Out of scope for v1 (roadmap)

Scheduled marketplace API ingestion (Amazon SP-API), XLSX and JSON report ingestion, human-approved auto-filing, run-to-run diff, shipment timeline view, multi-marketplace adapters, learning which claim types get paid.

Dropped for Round 2 and not planned: PDF and email report ingestion, and the Jev classification model (docs/ROUND2_PLAN.md, DECISIONS D-007).

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| No real dataset exists (seller data is private) | Organiser sample formats plus a held-out eval set labelled by two humans |
| LLM invents evidence or numbers | LLM never decides; validators on every output; no tool can set a verdict or amount |
| Evidence matched to the wrong SKU or unit | Exact-key retrieval and scope rules; sibling-SKU adversarial test |
| Solo build with limited time | Strict phase order, must-have tier first, wow features only if time remains |
| AI provider unavailable during demo | LLM-off mode with template explanations |

## 11. Assumptions

- Evidence records from other Managers are not changed after capture (a correction arrives as a new record or an override) and carry a record ID, a capture timestamp and entity references.
- A Manager's PASS covers only what that Manager checked.
- Amounts are in the report currency; no FX conversion inside a claim.
- If organisers provide their own data or schema, it enters through adapters and nothing downstream changes.
