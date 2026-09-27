# Backlog

Work agreed but not scheduled. Newest phase first.

## Phase 2

Both items were built on `day5` (2026-09-27): `totals` on `GET /decisions` shown in the KPI
tiles, and `GET /me` in the top bar; the sign-in workaround is removed.

Added 2026-09-27 by the human lead, during the Day 4 UI polish (`day4-polish`).

- **Per-decision totals from `GET /decisions`.** Return, for the whole run and per effective
  decision, the claimable total (sum of `claim_amount`) and the charged total, computed in the
  backend with Decimal. The UI then shows amounts on the KPI tiles; until then the tiles show
  counts only, because the UI never adds money up.
- **`GET /me`.** Return the organisation (id and display name) of the calling API key. The UI
  then drops its sign-in workaround, which reads `organization_id` from the newest decision
  record into an httpOnly cookie and shows "Signed in" for an organisation with no run.
