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

## Day 5 guardian review, deferred (docs/reviews/day5-guardian-findings.md)

Findings 1-12, 16 and 17 were fixed on `day5` (2026-09-27). The human lead moved these four
to the backlog rather than fixing them now.

- **13. Two llm-smoke tests depend on test order** (`test_llm_db.py:181-189`). Run alone, the
  fall-back test fails; the missing-settings test passes for the wrong reason and does not
  check the message. Fix: make each test self-contained (its own settings/state), and assert
  on the actual message in the missing-settings case.
- **14. Cache read and write errors are dropped silently** (`explain.py:98, 105`). A
  `SQLAlchemyError` on the cache lookup or write is swallowed with a bare `except`, costing
  at most a model call today, but the operator has no way to see a cache that is silently
  never being read or written. Record it in `fallback_reason` or an audit event.
- **18. `check-no-keys` only looks for `private_key`.** It should also flag database URLs
  with real passwords and other long secret-like values before they reach a commit.
- **19. Totals use today's engine config, not the run's** (`review.py:274`). Changing a
  charge type's `kind` later silently changes an old run's totals, and an unmapped charge
  type returns 500 instead of a clear error. Also untested: `LLM_TIMEOUT_S`/`LLM_RUN_BUDGET_S`
  `<= 0` is accepted by validation that only checks `< 1` is rejected (same thing, but
  untested at the boundary), the provider name comparison is case-sensitive
  (`LLM_PROVIDER=Vertex` is refused as unknown rather than normalised), and
  `automatic_function_calling` could be silently re-enabled by a refactor with nothing to
  catch it.
