# Pre-Round-2 design notes (archive)

**History only. This is not a description of what was built.**

These notes were written before the Round 2 rules were published. They are superseded by
`CLAUDE.md`, `docs/ROUND2_PLAN.md` and `ARCHITECTURE.md`, which describe the current scope
and the system as built. The PRD moved to `docs/product/PRD.md` and was revised to match.
Nothing in this folder is kept up to date, and nothing here should be read as a claim about
the implementation.

Known conflicts with the current build:

- Verdicts: 03 and 05 use six verdicts (SILENT, DUPLICATE, ALREADY_REIMBURSED, ...) and
  READY / NEEDS_REVIEW claim statuses. Round 2 uses `decision` (CLAIM / DO_NOT_CLAIM /
  REVIEW), `evidence_status` and `reason_code`, with check verdicts PASS / FAIL / UNCERTAIN.
- Evidence shape: 03 defines its own `EvidenceRecord` envelope (`manager`, `refs`, `body`,
  `content_sha256`). Round 2 uses the organisers' contract (`agent`, `subject`, `checks`,
  `content_hash`, ...).
- Eval: 10 (P11) gates on synthetic ground truth. Round 2 uses a held-out set labelled by
  two humans before the agent runs, with Cohen's kappa reported (`eval/`).
- Health endpoint is `GET /health` (07 and 10 say `/healthz`, `/readyz`).
- 10 (P8) adds PDF/email ingestion, and 16 and D-007 add Jev. Both are dropped for Round 2.
  Cross-pod contract negotiation is dropped too (organisers provide the contract).
- 12 and 14 use wording that CLAUDE.md forbids for current docs. It is left unedited here
  as a historical record.
