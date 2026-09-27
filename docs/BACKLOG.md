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

## Found during the Phase 2 fixes (2026-09-27), not yet fixed

- **`(D-0NN)` decision citations in `reason`/`next_action` text are read by the explanation
  validator as unrecognized IDs** (`backend/app/llm/validate.py`, `ID_SEPARATED`). The engine
  writes citations like `(D-021)`, `(D-016)`, `(D-011)` into several `reason`/`next_action`
  strings (`backend/app/engine/__init__.py`); the prompt tells the model to relay
  `next_action` verbatim, so a model that does so is wrongly rejected with "ID D-021 is not
  in the trace" every time, silently falling back to the template (fails safe, but degrades
  explanation quality on exactly the rows that most need a good one: ambiguous refunds,
  partial coverage, missing unit value). Pre-dates this session's fixes (the old, upper-case-
  only `ID_SEPARATED` pattern already matched `D-021`); found while adding
  `test_real_engine_next_actions_do_not_trigger_a_false_decision_signal`. Fix: exclude a
  `\(D-\d+[a-z]?\)` citation pattern from the ID checks, the way `DNC` is already excluded as
  "a phrase, not an ID".
- **ARCHITECTURE.md and docs/DECISIONS.md D-022 do not describe the validator or prompt
  changes made this session** (rules-guardian, Medium). The "Validation" section and diagram
  in ARCHITECTURE.md, and D-022's "Validation" and "Recorded on the decision" bullets in
  DECISIONS.md, still describe the pre-Phase-2 checks only: no mention of the case-
  insensitive anti-argument check (finding 2), the currency/percentage/number-word/negative-
  number/claim-amount checks (finding 6), `LLM_RUN_BUDGET_S` (finding 4), the overridden
  record getting its own explanation (finding 5), or the `<trace>` tags (finding 16). Fix:
  a dated D-022 amendment (matching the D-021 amendment style) and an ARCHITECTURE.md update.
- **`LLM_RUN_BUDGET_S` is not in `.env.example`** (rules-guardian, Low). Has a safe default
  (200), so not urgent; `LLM_TIMEOUT_S` has the same pre-existing gap.
- **The anti-argument and number-word checks are denylists, not exhaustive** (rules-guardian,
  Low). E.g. "it would be reasonable to pursue this fee" or "a third of the amount" bypass
  them. Cannot flip a decision (checked after it is fixed), but could show a human reviewer
  misleading text; same class of limitation the checks already document ("checks facts that
  can be checked mechanically... a sentence can still be wrong without naming a wrong ID or
  number", D-022).
- **`pipeline.py`'s `contextlib.suppress(Exception)` around the fail-open explanation call
  has no audit event or log for what failed** (rules-guardian, Low). Same class of issue as
  backlog item 14 (cache errors swallowed silently) — a second instance, not a regression.
