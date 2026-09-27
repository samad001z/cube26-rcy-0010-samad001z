# Day 5 guardian review findings (branch day5 at 58fcc42)

Source: rules-guardian and test-guardian review in the cloud session, 2026-09-27. No Critical findings, 3 High. Backend 412 passed, eval 46 passed. Mutation testing: 39 of 52 mutants caught, 13 survived.

## High

1. **Validator matches IDs and names as substrings** (validate.py:112). DEMO-F01-1 passes when the trace only has DEMO-F01-12; P-1 or R_CONTRADICTED pass against PRP-1 or R_CONTRADICTED_FULL. Lowercase IDs are never checked. Breaks rule 3. Fix: compare against a set of whole tokens from the trace; match ID patterns case-insensitively.
2. **An explanation can argue for a different decision than the record's** (validate.py:47-49, 93). Decision words only checked in capitals, so a REVIEW record can carry "You should claim the fee now" and a CLAIM record "do not claim this yet". The UI then labels that text "checked against this decision's evidence". Fix: reject decision words in any case that don't match the decision, including forms like "claim the", "file", "should be claimed".
3. **Tests can reach the network, including Vertex** (conftest.py:29-47). The proxy is on 127.0.0.1, so the loopback allowance lets traffic out (a guarded test got a real 401 from Google). Session-scoped fixtures run before the guard is installed. LLM_ENABLED and GOOGLE_APPLICATION_CREDENTIALS are inherited from the environment. connect_ex is not blocked. Fix: pin LLM and proxy env vars off before any fixture runs, block connect_ex, add a test proving an outbound HTTPS call fails.

## Medium

4. **One slow model can lose every charge in a run** (pipeline.py:232, cloudrun.sh --timeout 300). Sequential calls inside one transaction at up to 20 s each; 40 charges can exceed Cloud Run's 300 s limit and roll back everything, even pending records. Breaks rule 5. No test that a fail-open record gets its template explanation. Fix: a per-run time budget that falls back to the template once spent, or explain in a second step after decisions are committed.
5. **An overridden record keeps the engine's explanation and model_version** (review/__init__.py:113-131). A human DO NOT CLAIM can show text starting "REVIEW.". Fix: clear both on the overridden record, or label them as the engine's; add a test.
6. **Numbers and currencies aren't tied to their meaning** (validate.py). Passes today: "claim amount 12.50" when 12.50 is the charge, not the claim; "2.00 EUR" on a USD line; $ and euro symbols; "-6.25"; "two dollars"; "twice"; a lone month name. A mutant removing the check on single-run alphanumeric IDs (X00DEMO0001) survived. Fix: reject currency codes and symbols other than the trace's own, signs, percentages and number words; where a sentence says "claim ... amount", require the claim amount; add the missing ID test.
7. **An edited explanation would still pass the record's hash check** (decision.py:152-158). A mutant that always leaves the explanation out of the hash survived. Fix: a test that changing explanation.text makes verify_hash() fail.
8. **Cache behaviour untested.** Reusing cached text without re-validating survived; dropping model or prompt version from the cache key survived. Fix: a test with a bad cached row; tests that trace_hash changes with model and prompt version.
9. **Totals tests don't cover summing or currency.** Overwriting instead of adding survived; ignoring currency survived. Fix: a test with two CLAIMs and a second currency.
10. **Key-file credential untested** (vertex.py:31). Ignoring the key file (silent fallback to other credentials) survived. Fix: a test that the file's credentials reach the client.
11. **Eval report wrong once the model is on** (eval/run_eval.py:418). Prints "model cost per charge: $0.00" and "no model version" regardless; the call count includes cache hits and misses rejected calls. Fix: report recorded tokens, cost and calls.

## Low

12. **An explanation error can still hurt a decision** (explain.py:178-184, pipeline.py:238). The error branch rebuilds trace and template without a guard, so it could turn a valid decision into ENGINE_ERROR or abort the run on the fail-open path. Fix: a constant fallback text that cannot fail, and a guard around the fail-open call.
13. Two llm-smoke tests depend on test order (test_llm_db.py:181-189); run alone, the fall-back test fails; the missing-settings test passes for the wrong reason and doesn't check the message.
14. Cache read and write errors are dropped silently (explain.py:98, 105). Record them in fallback_reason or an audit event.
15. *(no separate item; numbering kept from the review)*
16. **Prompt doesn't mark the trace as data** (prompt.py). Report-supplied strings could carry instructions. Wrap the trace in tags and tell the model to ignore instructions inside them.
17. **Passwords on command lines** (DEPLOY.md:40, supabase.sql, bin/check-db). They land in shell history and the process list. Use .pgpass, PGPASSWORD from the environment, or pre-hashed SCRAM passwords.
18. check-no-keys only looks for private-key field. Add database URLs with real passwords and long secret-like values.
19. Totals use today's engine config (review.py:274): changing a charge type's kind later silently changes old runs' totals, and an unknown type returns 500. Also untested small settings: timeout <= 0 accepted, provider name case-sensitive, automatic function calling re-enabled.

## Confirmed fine by the reviewers

- The explanation step only changes explanation and model_version, and runs after the citation validator. Pending records never reach the model.
- Records stored before this change still verify.
- Totals are Decimal per currency, exclude refund lines and loss events, use overridden decisions, and ignore filters.
- llm_explanations has RLS enabled and forced, SELECT/INSERT only, and is in the isolation tests.
- No secrets in the image; the API never gets the owner password; no role is superuser or bypasses RLS.
- Response fixtures are labelled hand-written; no mock in the eval path.
- No forbidden language; migration 0005 is a new file.

## Human lead decision (2026-09-27)

- **Fix now, in this order:** 1, 2, 3 (the Highs), then 4-11, then 12, 16, 17.
- **Backlog (docs/BACKLOG.md):** 13, 14, 18, 19.
- Never run `make eval`; labels are not in yet.
