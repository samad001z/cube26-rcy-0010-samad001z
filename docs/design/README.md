# Design notes (older)

These notes were written before the Round 2 rules were published. Where they conflict
with `CLAUDE.md` or `docs/ROUND2_PLAN.md`, those two win. Known conflicts:

- Verdicts: 03 and 05 use six verdicts (SILENT, DUPLICATE, ALREADY_REIMBURSED, ...) and
  READY / NEEDS_REVIEW claim statuses. Round 2 uses `decision` (CLAIM / DO_NOT_CLAIM /
  REVIEW), `evidence_status` and `reason_code`, with check verdicts PASS / FAIL / UNCERTAIN.
- Evidence shape: 03 defines its own `EvidenceRecord` envelope (`manager`, `refs`, `body`,
  `content_sha256`). Round 2 uses the organisers' contract (`agent`, `subject`, `checks`,
  `content_hash`, ...).
- Eval: 10 (P11) gates on synthetic ground truth. Round 2 needs a held-out set labelled by
  two humans before the agent runs, with Cohen's kappa reported.
- Health endpoint is `GET /health` (07 and 10 say `/healthz`, `/readyz`).
- 12 and 14 use wording forbidden by CLAUDE.md ("production-grade", "tamper-evident").
- Jev (16, D-007), PDF ingestion and cross-pod contract negotiation are dropped or stretch.
