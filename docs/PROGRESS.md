# PROGRESS (context carry between sessions)

Update at the end of every session. Newest entry on top.

### 2026-09-27 - Deploy (Sydney) and final pre-eval pass, branch `main`

- Done, since the Day 5 Phase 2 entry below (`day5` merged to `main`):
  - **Eval: single-labeller mode.** `run_eval.py` now handles `labels_B.csv` absent or still
    blank (gold is `labels_A.csv` directly, agreement not computed, REPORT.md says so at the
    top and in a Limitations section) and refuses outright, naming how many rows are still
    blank, when `labels_B.csv` is partially filled in — never silently choosing a mode.
  - **Deploy region moved to Sydney**, next to the Supabase project (`ap-southeast-2`): Cloud
    Run `asia-south1` -> `australia-southeast1`, Vercel functions `bom1` -> `syd1`. Every
    region mention in `DEPLOY.md`, `deploy/cloudrun.sh` and `frontend/vercel.json` updated
    together; grepped clean afterwards.
  - **Deployed live**: API on Cloud Run (`australia-southeast1`), database on Supabase
    Postgres (`ap-southeast-2`), review UI on Vercel (`syd1`), model explanations on Vertex
    AI (`us-central1`, `gemini-2.5-flash`, via the Cloud Run service identity),
    `LLM_ENABLED=true` in production. Evidence, captured 2026-09-27:
    `docs/deploy/smoke-live-2026-09-27.txt` (23/23: authentication, tenancy isolation, the
    review UI end to end, against the live API and UI), `docs/deploy/check-db-2026-09-27.txt`
    (forced RLS on every table, the app role limited to `SELECT, INSERT`, no Data API role
    access, SSL), `eval/llm-smoke-2026-09-27.txt` (one real, validated Vertex AI call:
    `gemini-2.5-flash`, 4476 ms, 1325 in / 551 out tokens, 0.001775 USD estimate). Prices
    verified 2026-09-27 on Google's Vertex pricing page: $0.30 / 1M input, $2.50 / 1M output
    (thinking billed as output).
  - **Final pre-eval pass** (this session), one commit per task:
    1. Confidence on UNCERTAIN checks: on a live CLAIM (DEMO-F01-1), `within_filing_window`
       showed confidence 1.00 next to an Uncertain verdict. Confirmed the engine value is
       correct (D-015: confidence is deterministic per check, not a probability the outcome
       is favourable) and the gap was legibility. Fixed in the UI only: a focusable,
       tooltipped confidence value (`checks-card.tsx`, `lib/checks.ts`) explaining the
       semantic per verdict, ending "UNCERTAIN is not a low-confidence PASS" for UNCERTAIN;
       a documented-semantic paragraph added to ARCHITECTURE.md; a new
       `frontend/scripts/smoke-live.mjs` check. No engine value changed, no migration
       touched, no stored hash affected. Verified locally: 24/24 smoke checks.
    2. The one pytest warning (`StarletteDeprecationWarning`, httpx with `TestClient`) is a
       third-party deprecation; logged to `docs/BACKLOG.md` rather than adding a new
       test-only dependency this close to the deadline.
    3. `README.md` rewritten as a real project README (it had been the organisers' buildathon
       text with a small section prepended); eval numbers left as the required pending
       placeholder.
    4. `ARCHITECTURE.md` extended: components, a Mermaid deploy diagram, security, reliability
       and failure modes, and a table of every `docs/DECISIONS.md` entry.
    5. This entry.
    6. Hygiene: grepped the tracked tree for CLAUDE.md's forbidden words — every hit outside
       `backend/app/llm/validate.py` (the rule-checking code itself), its test, and archived
       or organiser rules material was none; no live violation found. `bin/check-links` added
       and run clean (fixed one pre-existing broken link in the archived
       `docs/round2-rules/README.md`). `make check-keys` and `make lint test` green.
- Tests/eval status: `make lint test` green throughout; counts unchanged from the Day 5 Phase
  2 entry (backend and eval suites untouched by this pass, aside from the new frontend
  headless check). `make eval` was not run: labels are not yet committed.
- Open issues: `docs/BACKLOG.md` has the current list, including the pytest warning above and
  the `(D-0NN)`-as-ID validator gap from the previous session.
- Next step: two humans label the held-out set independently, commit, `make eval`, fill in
  the Evaluation section's numbers.

### 2026-09-27 - Day 5 Phase 2 (guardian review fixes), branch `day5`
- Done: fixed the approved findings from `docs/reviews/day5-guardian-findings.md`
  (rules-guardian + test-guardian review of the Day 5 LLM layer, 2026-09-27), one commit
  per finding, `make lint test` after each:
  - **Highs:** (1) the explanation validator compared IDs/names against the raw trace
    string with `in`, so a substring match let a shorter, wrong ID pass, and its ID patterns
    were upper-case only, so a lower-case rendering was never checked; now whole-token sets,
    case-folded. (2) decision-word checking only looked in capitals, so lower-case wording
    arguing for a different decision ("you should claim the fee now" on a REVIEW record)
    passed; now also scanned case-insensitively. (3) the no-network test guard was a
    function-scoped fixture, so the session-scoped fixtures above it ran unguarded, and a
    loopback proxy could forward traffic out anyway; the guard is now installed at
    conftest.py import time, blocks `connect_ex` too, and proxy/LLM env vars are forced off.
  - **Mediums:** (4) a per-run time budget (`LLM_RUN_BUDGET_S`) so one slow model cannot
    exceed the deploy's request timeout and roll back a whole run. (5) an overridden record
    now gets its own explanation and clears `model_version`, instead of keeping the engine's.
    (6) numbers/currencies are now tied to their meaning: no currency symbol or wrong code,
    no percentage, no number word, no negative number, and the figure nearest "claim" must be
    the claim amount. (7)-(10) tests added for previously-surviving mutants (explanation
    hash, cache re-validation and its key, a two-currency totals sum, the Vertex key file's
    credentials reaching the client) - each confirmed to catch its mutant by hand. (11) the
    eval report's model-cost line always printed "$0.00" and "no model version"; it now
    reads each decision's own recorded tokens/cost/model id and separates real calls from
    cache hits.
  - **Lows:** (12) the explanation fallback path itself could raise (build_trace/_template
    unguarded), and pipeline.run_org's fail-open path had no guard around its own call to it;
    both now guarded, with a constant last-resort text that cannot fail. (16) the prompt now
    wraps the trace in `<trace>` tags and tells the model to ignore instructions inside it
    (report-supplied strings reach the trace). (17) `deploy/supabase.sql` and `bin/check-db`
    no longer take passwords as command-line arguments (psql `\getenv`, `CHECK_DB_URL` env
    var); verified against a scratch database in the local Postgres container.
  - Findings 13, 14, 18, 19 moved to `docs/BACKLOG.md` (human lead decision).
  - `make eval` was not run (labels still not in).
- Reviews of the fixes themselves (rules-guardian, test-guardian; see the real output pasted
  into this session's transcript):
  - rules-guardian: no Critical or High. One Medium (ARCHITECTURE.md and D-022 did not
    describe the new validator/prompt/override/budget behaviour) fixed with a dated D-022
    amendment and an ARCHITECTURE.md update. Three Low findings added to `docs/BACKLOG.md`
    (`LLM_RUN_BUDGET_S` missing from `.env.example`; the anti-argument checks are
    non-exhaustive denylists; the fail-open explanation guard swallows errors with no audit
    trail, same class as backlog item 14). Confirmed: the decision/amount/citation path is
    untouched by every change (rule 2); the override change is a read-time derived view, not
    a rewrite of stored data (rule 11); the fail-open path stays safe (rule 5); no secret was
    introduced (rule 14); the trace is now delimited in the prompt (rule 10 concern, finding
    16, already fixed).
  - test-guardian: no dishonesty (no weakened tests, no fixture/label edits, no mocks in the
    eval path, no new skip/xfail); real `make test` output matched the claimed counts. One
    gap: the manual check that findings 2/6 don't false-positive on the engine's real
    `next_action` text (with its literal "(D-021)" citations) was not an automated test.
    Writing that test found a genuine regression from finding 2: the engine's own
    R_REIMBURSEMENT_AMBIGUOUS advice ("...close the line as do not claim (D-021)") was
    wrongly read as arguing DO_NOT_CLAIM on a REVIEW record. Fixed (`_OVERRIDE_ADVISORY`
    strips that phrase before the signal check runs) and covered by a new test against
    `_decision_signals()` directly, since a separate pre-existing gap — `(D-0NN)` citations
    read as unrecognized IDs by the ID check — would otherwise reject the same text for an
    unrelated reason; that gap is now tracked in `docs/BACKLOG.md`, not fixed (out of the
    scope the human lead set for this session).
- Tests/eval status: `make lint test` green throughout, one commit at a time; 439 backend
  and 48 eval tests at the end (up from 412 and 46 at the start of the session).
- Next step: human lead reviews this session's fixes, the two guardian reports and the new
  `docs/BACKLOG.md` items (the `(D-0NN)`-as-ID gap chief among them); labelling still blocks
  `make eval`.

### 2026-09-27 - Day 4 polish (review UI design pass, demo data), branch `day4-polish`
- Done:
  - Frontend only; no backend, engine or migration change. `make eval` not run.
  - UI foundations:
    - Radix primitives written in shadcn/ui style (the shadcn registry answers 403 here);
    - lucide-react icons, and Geist Sans / Geist Mono through the `geist` package;
    - light and dark tokens following the system;
    - CLAIM green, DO NOT CLAIM slate, REVIEW amber, always shown with an icon and the word.
  - App shell: sidebar, and a top bar with the run switcher, org name and sign-out.
    - The org name is read at sign-in from the newest decision record into an httpOnly cookie, since no endpoint returns it.
  - Sign-in card: show/hide key, error state, note on how the key is stored.
  - Decisions list:
    - count tiles of equal weight;
    - TanStack Table 9: sortable, sticky header, URL filters applied by the backend, ID search, 25 rows a page;
    - cards below 1024px;
    - skeletons, empty and error states.
  - `src/lib/reasons.ts`: a plain-English headline for each of the 22 rule ids the backend emits, falling back to the engine's reason.
  - Detail page:
    - Why box, with the engine's reason under Technical detail;
    - checks list;
    - evidence timeline with custody-window rails, cited records solid and read-only ones dashed;
    - deadline card, and Record integrity with copy buttons;
    - override side sheet that shows the backend's CLAIM refusal, and a history timeline.
  - Demo data in `demo/`, 10 lines, all `org_demo_alpha`, `DEMO-` IDs:
    - nothing taken or derived from `data/` or `eval/`;
    - `make demo` runs it and `demo/check.sh` pins each line;
    - "Load demo data" is on Run a report;
    - no outcome depends on the run date.
  - Human lead decisions (2026-09-27):
    - demo is alpha only;
    - tiles show counts only, with no money arithmetic in the UI;
    - the check is a script, not a backend test.
  - Backlog in `docs/BACKLOG.md`: Decimal totals from GET /decisions, and GET /me.
  - Screenshots of the demo run are in `docs/screenshots/`, light and dark; README and frontend/README updated.
- Tests/eval status:
  - Frontend:
    - `npx eslint` clean; `npx next build` passes.
    - `node scripts/contrast.mjs`: every token pair is at least 4.5:1 in both themes.
  - Screenshot script against `next start`: no console errors, no sideways scroll at 375px on any page, a solid 2px focus outline after Tab.
  - Headless check:
    - Load demo data made a run with 3 CLAIM, 3 DO NOT CLAIM and 4 REVIEW;
    - the decision filter and search work;
    - a bravo override was saved and shows in the history;
    - the key cookie is invisible to `document.cookie`.
  - `make lint test` green: 358 backend and 46 eval tests, unchanged.
  - `make demo`: 10 lines = 3 CLAIM, 3 DO_NOT_CLAIM, 4 REVIEW, check passed.
- Open issues:
  - A run decides every charge stored for the org. On a database where the alpha sample was already loaded, the demo run also contains those 40 lines. `check.sh` looks only at `DEMO-` lines.
  - The org name needs a run to exist first; GET /me is in the backlog.
  - The earlier open issues stand, labelling above all.
- Next step: human lead reviews and merges `day4-polish`; labelling; Day 5 LLM layer and deploy.

### 2026-09-27 - Day 4 (review UI, overrides hardened, fail-open end to end), branch `day4-ui`
- Done:
  - `day4-ui` from `origin/main`, with `day4-review`'s two commits cherry-picked (override flow, review endpoints, Next.js UI).
  - D-021 approved by the human lead as written on 2026-09-27, then amended (stricter only) after the second rules-guardian review. The amendment (A1, A2, A3) was approved by the human lead on 2026-09-27.
  - Human CLAIM override is refused for:
    - pending records, loss events and fee refund lines;
    - an amount that is not the charge itself (claim_basis not full_amount, or amount_computable not PASS);
    - a filing window that is FAIL, whether at the run or on the override day;
    - reimbursements not settled, or changed in the store since the run;
    - any decision other than the newest one for its line.
  - Otherwise it goes through the citation validator; only "cites contradicting evidence" is skipped, because the stored reason stands in for it.
  - Reproduced and closed: sample FEE-0071-2 (a loss event past its deadline) had been accepted as a 14.00 USD human CLAIM.
  - History check covers the list, the line history and every new override: hash chain, recomputed claim cap, and row columns against body. `earlier_override` flags overrides made on older runs.
  - `NEXT_UNIT_VALUE` reworded ("file the claim outside Alibi; loss-event claims cannot be made through an override"). The partial-coverage and ambiguous-refund next actions were reworded the same way.
    - Sample decisions, rules, reason codes and counts are unchanged against the pre-change baseline: alpha 39 REVIEW / 1 DO_NOT_CLAIM, bravo 20 / 1.
    - next_action changed on 2 alpha lines, so their content hashes changed.
  - Both override limitations are in ROUND2_PLAN's README assumptions list.
  - Gaps from the Day 4 spec, all built:
    - (5) Equal-weight CLAIM / DO NOT CLAIM / REVIEW tiles.
    - (6) Plain-English check names, with custody-window and deadline sentences. The deadline is judged today, with the run's own check shown beside it.
    - (8) `make review-ui`: one command, bound to 127.0.0.1, dev-only keys, refuses a non-local database. Documented in README.
    - (3) Fail-open end to end through POST /agent and GET /decisions.
    - (1)(4) Filters by effective decision, charge type and rule, in API and UI.
    - (2) `captured_at`, `custody_window` and `deadline` fields.
    - (7) `earlier_override` shown on the list.
    - (9) Headless browser check.
  - ARCHITECTURE has a review, override and UI section.
- Reviews:
  - rules-guardian, three passes.
    - First pass: 2 Critical (a human CLAIM bypassed every guard), 3 High, 2 Medium, 3 Low. All fixed or documented.
    - Second pass: 2 High (a full-fee claim on a fee_difference charge; the store and date not re-checked), 3 Medium, 4 Low. All fixed.
    - Third, focused pass on the fixes: no Critical or High. Fixed its 1 Medium and 3 Low:
      - a partially covered charge could be claimed in full; now refused (A3), and the next action is reworded;
      - clearer message when the window has opened since the run;
      - D-021 now states the post-insert re-check's limit exactly;
      - stale docstrings.
  - test-guardian, three passes.
    - First pass: the API override test only restored the engine's own decision; now fixed. Plus grant, ordering, raw-row and tamper tests.
    - Second pass: 25 of 56 mutants survived in the new code. Tests were added and all 33 targeted mutants are now caught.
    - Third pass: nothing weakened, snapshot untouched; 5 of 14 mutants survived. Tests were added and all 6 re-run mutants are now caught:
      - the override day with a real (patched-in) sourced window;
      - the post-insert race guard;
      - the charge-hash guards on deadline and custody window.
      - Date checks tolerate a midnight crossing.
- Tests/eval status:
  - `make lint test` green: 358 backend and 46 eval tests on Postgres 16.
  - `next build` passes.
  - Headless Chromium against `make review-ui`, all passing, no console errors:
    - sign-in and wrong-key refusal; cookie invisible to page JS;
    - filters;
    - plain-English detail page;
    - override saved and its history shown;
    - CLAIM not offered on a weight-tier fee or a loss event, with the reason shown;
    - phone width with 0px overflow.
  - `make eval` and anything on eval/ data were never run: the labels are still blank.
- Open issues:
  - Two humans still need to label `eval/labelling_sheet.csv` before `make eval`. This is the blocker for the evaluation section.
  - The post-insert newest-decision check does not catch a run committing between it and the override's commit (`run_org` takes no lock); that override then shows as `earlier_override` on the new run.
  - Reviewer identity is self-declared (the org key identifies an organisation, not a person).
  - Loss-event claims are filed outside Alibi.
  - The fail-open e2e test raises OperationalError from `decide` while the database stays up. It does not cover a real lost connection, where writing the pending row could fail too.
  - Migration 0004 was edited in place (the blank-reason constraint). A dev database already at 0004 keeps the old constraint: run `alembic downgrade 0003 && alembic upgrade head`. The test DB is rebuilt each run.
  - `alibi_test` is shared: two concurrent `make test` runs clobber each other. A per-run database name would fix it.
  - No request-size limit in front of the app yet (deploy work).
- Environment: no Docker. Postgres 16 is the container install, with roles and databases from `docker/postgres/init.sh`. Node 22 was preinstalled; Playwright 1.56 is global, with Chromium in /opt/pw-browsers. The push needed the repo added to the session's GitHub scope.
- D-021 amendment (A1, A2, A3) approved by the human lead on 2026-09-27. New rule 15 in CLAUDE.md: schema changes go in new migrations only; existing migrations are never edited.
- Next step: human lead merges `day4-ui`; labelling; Day 5 LLM layer and deploy.

### 2026-09-26 - Day 4 (overrides, review endpoints, review UI), branch `day4-review` (cherry-picked onto `day4-ui` on 2026-09-27)
- Done:
  - Override flow (D-021, proposed): `decision_overrides` table (migration 0004), append-only, forced RLS, FK to the decision, database checks (no-op, claim amount, blank reason or reviewer, unique sequence). `app/review`: effective record, hash chain re-checked on every read and before every override, human CLAIM = charged minus reimbursed, refused on pending records and when nothing remains, advisory lock per decision. Audit event `DECISION_OVERRIDDEN`. Closes triage finding 11.
  - Review endpoints behind the same API key and RLS: `GET /runs`, `GET /decisions[?run_id=]`, `GET /decisions/{id}` (charge, evidence trail with hash checks, override history, integrity problems, line history), `POST /decisions/{id}/overrides`. Another org's record answers 404. A dead database answers 503.
  - Review UI (`frontend/`, Next.js 16): sign-in with the org key into an httpOnly cookie, decisions table (REVIEW first, counts, why-review breakdown, filters, run picker), decision detail, override form, upload page for new runs. Light and dark, phone width checked.
- Tests/eval status: `make lint test` green: 304 backend and 46 eval tests on Postgres 16 (46 new: overrides and review API, including concurrency, tampered history, DB constraints, cross-org 404s, 503s). Mutation check on `app/review`: 6 of 6 mutants caught (the lock test first survived because the race never happened; the test now forces the overlap). Frontend: `eslint` clean, `next build` passes. End-to-end in headless Chromium against a live backend: redirect to sign-in, bad key refused, cookie httpOnly and invisible to `document.cookie`, DO_NOT_CLAIM and CLAIM overrides saved and shown, no console errors. `alibi run` counts unchanged. No eval result yet (labels still blank).
- Not done: rules-guardian and test-guardian reviews of this branch were not run in this session. Branch not merged.
- Open issues:
  - Two humans still need to label `eval/labelling_sheet.csv` before `make eval`. This is the blocker for the 25-point evaluation section.
  - Reviewer identity is self-declared (org key, not a person).
  - Overrides do not carry across re-runs; the detail page shows earlier runs of the line.
- Next step: human lead reviews D-021 and merges `day4-review`; labelling; Day 5 deploy and LLM layer.

### 2026-09-25 - Day 3 (eval set, harness, POST /agent), branch `day3-eval`
- Done:
  - Task 0: `docs/design/` archived to `docs/archive/pre-round2-design/` (README: history only). PRD moved to `docs/product/PRD.md` and aligned with the build: F1 CSV only, no PDF/email, no Jev, the vocabulary, held-out eval, no forbidden wording. References updated (CLAUDE.md, ROUND2_PLAN, DECISIONS, rules-guardian, /phase).
  - Task 0b: `docs/reviews/copilot-pr14-triage.md` checks all 13 findings against the code. Two were still valid and are now fixed: the evidence key (D-018: `(org, agent, record_id)`, migration 0003, citations carry the pod) and API auth (Task 4). One stays open for Day 4 (the override flow). The rest were already fixed or are moot.
  - Task 1 (D-019): the refund returns custody window is now -60/+120 days, matching the sourced filing window. `check_windows_consistent` refuses a config where they drift apart. An unresolved unit gives `evidence_present` and `evidence_in_custody_window` UNCERTAIN, "unit not resolved". Sample counts and snapshot unchanged: the sample has no unresolved units, and its returns are all at +0 days. One pre-existing test moved from +69 to +121 days, approved by the human lead.
  - Task 2: `eval/`, 58 report lines on 52 units, both orgs, all 5 charge types. About 12 lines are plausible CLAIMs (stated defects across five prep checks, repeated fees of both fee types, a partial refund). Identifiers are shuffled, and no expected answers are recorded anywhere. `make_sheet.py` builds `labelling_sheet.csv` through the adapter and the sourced deadlines only, and shows every verdict with its recorded raw value. `labels_A.csv` and `labels_B.csv` are blank templates. `eval/README.md` says how the cases were chosen and states the limitation that the same author wrote the engine and the cases.
  - Task 3: `eval/run_eval.py` (`make eval`). It refuses unless the labels, sheet and data are committed and unchanged. It reports agreement and kappa before resolution, computes no agent metric while any disagreement is unresolved, then runs the real pipeline on a fresh `alibi_eval` DB and writes REPORT.md. Exit 4 means at least one false claim; exit 5 means a charge got no decision. Built, **not run on the eval set**.
  - Task 4 (D-020): `POST /agent` takes multipart uploads and returns the CLI JSON. `X-API-Key` is hashed and compared with `compare_digest`. The org comes only from the key; the date is today (UTC); the config is checked before any write. `alibi api-key` makes a key; `.env.example` has the `ALIBI_API_KEYS` placeholder (empty means 401 to everyone).
  - Also: `pod_file()` finds `<pod>_*.csv`, and `RunResult.latency_ms` measures latency per charge.
- Reviews:
  - rules-guardian: no Critical or High findings, and no path to a wrong CLAIM. Its 2 Medium findings are fixed: inputs frozen after labelling, and the config checked before any API write. Its Low findings are fixed too: the API doc wording, `as_of` removed from the API, the engine.yaml comment, raw values on the sheet, dropped charges fail the eval, dates corrected, other orgs' bad rows no longer stored.
  - test-guardian: nothing pre-existing was weakened and the snapshot is untouched; 16 of 21 mutants were caught. The 3 meaningful survivors now have tests, and I re-mutated each to confirm it is caught. It also found the PRD's 0-false-claim gate was not enforced; `run_eval` now exits 4. It noted the late-return eval case was written just after the D-019 fix, which is now disclosed in eval/README.md.
- Tests/eval status: `make lint test` green: 257 backend and 43 eval tests passed, on Postgres 16. `make eval` refuses, as intended, because the labels are blank. `alibi run` (as of 2026-09-25): alpha 40 lines = 0 CLAIM, 1 DO_NOT_CLAIM, 39 REVIEW; bravo 21 lines = 0 CLAIM, 1 DO_NOT_CLAIM, 20 REVIEW. Both unchanged. No eval result yet.
- Open issues:
  - The human lead reviews `eval/labelling_sheet.csv`, then two humans label independently and commit, and only then `make eval` runs.
  - Day 4: the override flow (triage finding 11).
  - No request-size limit in front of the app; the multipart body is parsed before the key check (D-020). That is deploy work.
  - The dates of the Round 2 plan are ahead of the calendar: all Day 1-3 work was done on 2026-09-25. The eval's fixed as-of date is 2026-09-27.
- Environment: this cloud session has no Docker. Postgres 16 runs from the container install, and `alibi_eval` was created by hand (`docker/postgres/init.sh` now creates it).
- Follow-up (same day, after the human lead reviewed the sheet): appended section 9 "Reading the sheet" to `eval/LABELLING_GUIDE.md` (nothing above it changed). The harness now reads only case_id, label and reason from the label files, so a Google Sheets or Excel CSV export works (BOM, CRLF, quoting, column order ignored); the sheet itself is still checked against the data. As-of 2026-09-27 comes from `eval/common.py:21` and is used at `eval/run_eval.py:204`; a test pins the sheet's and the harness's date together. `make lint test` green: 257 backend and 46 eval tests passed.
- Next step: two humans label independently, commit, `make eval`. Then Day 4: review UI, overrides, fail-open tests.

### 2026-09-25 - Day 2 fixes, branch `day2-fixes`
- Done:
  - Task 1 (D-016): claim direction for loss events. `evidence_status` is now always relative to what the line asserts; lost inbound and damaged in warehouse were inverted. Loss events map per charge type through `config/engine.yaml` `loss_event_outcomes` (one commented row each) and are never CLAIM. A refund counts as returned complete only when identity, parts and condition all PASS; anything else is REVIEW, "possible separate claim". A lost unit seen later is REVIEW, `R_LOSS_DOUBTFUL`. A known passed deadline on a loss event is DO_NOT_CLAIM, `FILING_WINDOW_EXPIRED`. Next actions on refuting rows never steer towards claiming.
  - Task 2 (D-017): the first sourced rule values, from the 2024 Seller Central announcement pasted by the human lead (caveat: may be superseded). Damaged in warehouse closes at 60 days; refund, item not returned, opens at 60 and closes at 120; the two removal-claim rules are stored under `unmapped_rules`. `posted_date` stands in for the source's event date, and every reason says so. New rule 1 `R_FILING_WINDOW_NOT_OPEN`: REVIEW, `FILING_WINDOW_NOT_OPEN`.
  - Task 3: the CLI prints "routing confidence" (defined in ARCHITECTURE.md). `evidence_in_custody_window` is UNCERTAIN "no relevant evidence to check" when `evidence_present` is FAIL. A missing setting prints one line ("copy .env.example to .env") and exits 2.
  - `ENGINE_VERSION` is now 0.3.0.
- Reviews:
  - test-guardian: 7 of 8 mutations were caught; the 8th was refused by config validation. Added the missing "parts not recorded" test and removed a `type: ignore`.
  - rules-guardian: no breach of the core rules. Folded in: damaged is SUPPORTED only with every prep check PASS; a lost-inbound sighting needs identity PASS; the validator refuses any CLAIM on a loss event; next actions reworded, with a case-insensitive guard test; stale rule numbers fixed.
- Tests/eval status:
  - `make lint test` green, 217 passed on Postgres 16.
  - `alibi run` as of 2026-09-25: alpha 40 lines = 0 CLAIM, 1 DO_NOT_CLAIM (FEE-0071-2, deadline passed), 39 REVIEW. Bravo 21 lines = 0 CLAIM, 1 DO_NOT_CLAIM (FEE-0048-2, item returned complete), 20 REVIEW.
  - Regression snapshot re-approved by the human lead (it is not ground truth). No eval yet.
- Open issues:
  - Still unsourced: filing windows for lost inbound and both fee types, and the fee schedule.
  - The `posted_date` proxy is an assumption until a report carries the event date.
  - The refund custody window (60 days either side of posting) is narrower than the 60-120 day filing window. A return arriving between 60 and 120 days after posting would be outside the custody window (REVIEW). Revisit with the eval set.
  - With an unresolved unit, `evidence_present` shows PASS with the resolution failure as detail. Pre-existing, left as is; flag for Day 3.
  - Official contract document still missing (D-008).
- Environment: Docker is not available in this cloud session. Postgres 16 ran from the container's own install (`/usr/lib/postgresql/16`) using `docker/postgres/init.sh`. No repo change.
- Next step: Day 3: held-out eval set labelled by two humans BEFORE the agent runs, eval harness, POST /agent.

### 2026-09-25 - Day 2 (P4-P7, headless CLI), branch `day2-engine`
- Done: pre-checks (duplicate fingerprint, already-reimbursed heuristic, filing window from sourced rules only), unit resolution, retrieval with custody windows, rule engine (8 handbook checks, 17 ordered rules, deterministic confidence), Decimal claim amounts, citation validator re-reading from Postgres (fails closed to REVIEW/pending), `decisions` table (migration 0002, forced RLS, append-only), fail-open per charge, audit events, `alibi run` and `make run ORG=...`. Decisions D-011 (resolved), D-013 (Option C defect_category), D-014 (filing window), D-015 (engine choices). ARCHITECTURE.md started (decision path, rules, confidence).
- Reviews: rules-guardian found 2 rule-9 breaches in refund matching (a refunded duplicate was claimed again; one fee absorbed refunds of other shipments). Both are reproduced in tests and fixed, and ambiguous refunds now go to REVIEW. Its suggestions were applied: fail-open hardening, a reason code on dependency errors (now DEPENDENCY_UNAVAILABLE, D-015c), non-final records treated as uncertain, validator scope and reimbursement checks, bool rule values refused. test-guardian found no weakened tests but a loose CLI test; that test now checks every printed block against the stored decision for both orgs. It also led to a sample rule-count snapshot (regression only).
- Human decisions after review: D-015a (a passed deadline is DO_NOT_CLAIM with FILING_WINDOW_EXPIRED), D-015b accepted, D-015c (new reason codes DEPENDENCY_UNAVAILABLE and ENGINE_ERROR; CLAUDE.md vocabulary updated). The sample snapshot is approved as a regression check (`test_regression_snapshot_sample`); it is not ground truth and is excluded from eval metrics.
- Tests/eval status: `make lint test` green, 182 tests on Postgres 16. Hypothesis: 200 examples each for the claim cap and the engine invariants (including "engine output always passes the validator"). Mutation check: disabling validator enforcement fails 2 tests. Acceptance: `alibi run` decided and printed 40/40 alpha and 21/21 bravo lines, each with evidence, checks and reason. All 61 are REVIEW: 42 weight-tier with no measurements (NO_RELEVANT_EVIDENCE), 10 loss events (D-011), 7 inbound defect fees with all prep checks passed but no defect_category (D-013), 2 inbound defect fees with an UNCERTAIN label/barcode check. No eval yet.
- Open issues: all channel rule values in `config/rules/amazon_us.yaml` are null. This environment's egress policy blocks sellercentral.amazon.com, so the human lead will paste verbatim excerpts: a filing window for each of the 5 charge types, and the fulfilment fee schedule. Until then every decision carries "filing deadline not verified". The sample has no `defect_category`, so no sample line can be CLAIM. The branch is pushed to origin (the fork). Docker Hub rate-limited `postgres:16` in the cloud session; the image was pulled from `mirror.gcr.io/library/postgres:16` and tagged locally (no repo change). The official contract document is still missing (D-008).
- Next step: Day 3: held-out eval set labelled by two humans BEFORE the agent runs, eval harness, POST /agent.

### 2026-09-25 - Day 1 (P0 + P1)
- Done: backend scaffold (FastAPI `/health`, Postgres 16 in docker-compose with `alibi_owner`/`alibi_app` roles, CI workflow, Makefile). Contract and charge models, content hashing, Decimal money. CSV-to-contract adapter with a reviewable mapping file and quarantine. Alembic schema with forced RLS on all 6 tables, org-scoped sessions, `alibi ingest` CLI. Decisions D-008 to D-012.
- Tests/eval status: `make lint test` green, 63 tests (19 in the Postgres isolation file). A mutation check (RLS removed from one table) made 6 tests fail. No eval yet.
- Open issues: `.env.example` not written (the `Read(./.env.*)` deny rule blocks that filename). Official contract document still missing (D-008). Zero-amount rule (D-011). CI workflow not yet run on GitHub. Nothing pushed.
- Next step: Day 2: pre-checks, unit resolution, evidence retrieval, rule engine, claims and citation validator, `alibi run`.

## Template
### YYYY-MM-DD HH:MM - Phase Pn
- Done:
- Tests/eval status:
- Open issues:
- Next step:
