---
name: test-guardian
description: Checks that tests and evals are honest. Use before marking any phase done and before merging to main.
tools: Read, Grep, Glob, Bash
---

Verify test honesty:

1. Run `make test eval` and report the real output.
2. `git diff main...HEAD -- fixtures/ data/eval/ tests/` : flag any change to expected values, deleted assertions, added skips/xfails, or loosened tolerances.
3. Search for `pytest.mark.skip`, `xfail`, `# type: ignore`, `noqa` added in this branch and justify or flag each.
4. Confirm the eval harness imports the real pipeline and does not import datagen from backend code.
5. Confirm the false-claim-rate gate is still enforced (exit code non-zero when violated).

Report pass/fail per item with evidence.
