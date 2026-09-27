#!/usr/bin/env bash
# Checks a demo run (the --json output of `alibi run` on demo/) shows what the demo data was
# built to show: every line decided as designed (demo/README.md), so at least 3 CLAIM,
# 2 DO NOT CLAIM and some REVIEW. Run by `make demo`. Exit 1 on any difference.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
cd "$ROOT/backend"
uv run python - "$RUN" <<'PY'
import json
import sys
from collections import Counter

# line_id -> (decision, rule_id), as designed in demo/README.md
EXPECTED = {
    "DEMO-F01-1": ("CLAIM", "R_CONTRADICTED_FULL"),
    "DEMO-F02-1": ("CLAIM", "R_CONTRADICTED_FULL"),
    "DEMO-F04-1": ("REVIEW", "R_NO_RELEVANT_EVIDENCE"),
    "DEMO-F04-2": ("CLAIM", "R_DUPLICATE"),
    "DEMO-F05-1": ("DO_NOT_CLAIM", "R_SUPPORTED"),
    "DEMO-F06-1": ("DO_NOT_CLAIM", "R_ALREADY_REIMBURSED"),
    "DEMO-F06-2": ("DO_NOT_CLAIM", "R_FEE_REFUND_LINE"),
    "DEMO-F07-1": ("REVIEW", "R_DEFECT_CATEGORY_MISSING"),
    "DEMO-F08-1": ("REVIEW", "R_LOSS_DOUBTFUL"),
    "DEMO-F09-1": ("REVIEW", "R_EVIDENCE_OUTSIDE_WINDOW"),
}

records = json.load(open(sys.argv[1]))
got = {r["subject"]["line_id"]: (r["decision"], r["rule_id"]) for r in records}
problems = [
    f"{line}: expected {want[0]} {want[1]}, got {' '.join(got[line]) if line in got else 'no decision'}"
    for line, want in EXPECTED.items()
    if got.get(line) != want
]
problems += [f"{line}: not in the demo design" for line in got if line not in EXPECTED]
counts = Counter(d for d, _ in got.values())
print(
    f"demo: {len(got)} lines = {counts['CLAIM']} CLAIM, "
    f"{counts['DO_NOT_CLAIM']} DO_NOT_CLAIM, {counts['REVIEW']} REVIEW"
)
for line in sorted(got):
    print(f"  {line:<11} {got[line][0]:<13} {got[line][1]}")
if counts["CLAIM"] < 3 or counts["DO_NOT_CLAIM"] < 2 or counts["REVIEW"] < 1:
    problems.append("the run does not show at least 3 CLAIM, 2 DO_NOT_CLAIM and 1 REVIEW")
if problems:
    print("demo check FAILED:", *problems, sep="\n  ")
    sys.exit(1)
print("demo check passed")
PY
