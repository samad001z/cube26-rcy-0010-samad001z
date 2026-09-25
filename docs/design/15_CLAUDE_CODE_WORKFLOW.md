# 15 Claude Code Workflow

## Straight answer first

Pasting these files and typing "read everything and build it" will **not** produce a working, production-grade project on its own. It will produce a lot of code quickly, and some of it will be quietly wrong. The known failure modes on a project this size:

- **Context drift.** After a few hours the early rules fall out of working context. The agent starts "helpfully" letting the LLM decide things or loosening a rule.
- **Green-test cheating.** When a test fails, agents sometimes edit the test, the fixture, or add a special case for the fixture's ID. On this project that silently destroys your 0% false-claim guarantee.
- **Fake completeness.** Mocked components, `TODO` stubs, and "should work" reports without running anything.
- **Silent design choices.** It picks a date parser, a rounding mode, or a matching heuristic without telling you, and it is the wrong one.
- **Parallel collisions.** Four teammates running four sessions on the same files break each other.

The docs pack already defends against these (rules 11-14 in CLAUDE.md, phase gates, eval gate). The rest is how you drive it.

## The operating loop (per phase)

1. Fresh session (or `/clear`). Run `/phase P5` (custom command in `.claude/commands/phase.md`).
2. The agent reads CLAUDE.md, PROGRESS.md and the phase, and proposes a plan in plan mode. **You read the plan.** Reject anything that touches files outside the phase.
3. Let it implement. Interrupt early if it starts editing fixtures or ground truth.
4. When it says done, run the acceptance command yourself. Do not trust the summary.
5. Run `/review-engine` (spawns the `rules-guardian` subagent) for any phase touching `engine/`, `claims/`, `agent/`.
6. `/checkpoint`: updates PROGRESS.md, commits, and you move on.

One phase per session. Sessions short and focused. PROGRESS.md is the memory between them.

## Where humans must stay in the loop

| Area | Why a human must check |
|---|---|
| Aggregation rules R0-R11 | This is the product. Read every rule function against docs/05. |
| Amount calculation | Money bugs are the worst demo moment. Hand-check 5 claims. |
| Fixtures and ground truth | Written by humans (or reviewed line by line). The agent must not author its own answer key and then pass it. |
| Prompts | Read every prompt file; check injection handling. |
| Demo dataset story | Curate it by hand so the demo tells a clean story. |

## Parallel work across the team

- Each teammate uses a separate git worktree and branch: `git worktree add ../rm-engine feat/engine`.
- P1 (models) is done together first and merged before anyone branches. Models are the interface between everyone.
- Ownership: only the engine owner's sessions may edit `engine/` and `claims/`. Others open an issue instead.
- Merge to main only when `make lint test eval` passes on the branch.

## Useful Claude Code settings

- Use plan mode for every phase start.
- Allow `make`, `pytest`, `ruff`, `mypy`, `git`, `docker compose` without prompts; keep file deletion and `git push` on ask.
- Keep `docs/` and `fixtures/` edits on ask for all sessions except the fixtures owner.

## Kickoff prompt (first session only)

```
Read CLAUDE.md, README.md and every file in docs/ in numeric order. Do not write code yet.
Then give me:
1. A one-paragraph summary of what we are building and the non-negotiable rules.
2. Any contradictions or gaps you found between the docs.
3. Your plan for phase P0 only.
Wait for my approval before writing any file.
```

If its summary misses the rules about verdicts, evidence and fixtures, stop and make it re-read. That tells you it will drift later too.
