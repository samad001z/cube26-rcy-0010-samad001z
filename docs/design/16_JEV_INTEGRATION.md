# 16 Jev Integration

Jev is TypeSafe AI's "System One" decision model. It answers typed questions (Choice, Score, Noul) about a shared `state` and returns calibrated probabilities. It generates no text. API: `POST https://api.typesafe.ai/v1/systemone`, model `jev-latest`, key in `TYPESAFE_API_KEY`. Read the live docs before coding: `https://docs.typesafe.ai/api.md` and `https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md` (append `.md` to any docs URL for markdown).

## Availability (checked 2026-09-24)

TypeSafe paused new Jev signups on 2026-09-22 due to demand; existing accounts keep working. Therefore:

- **Default for this build: `JEV_ENABLED=false`.** J1-J3 run on Claude Haiku with enum outputs and sentence-choice quotes (same pre-split sentence trick, so quotes stay verbatim by construction). Nothing in the MUST tier depends on Jev.
- If any teammate already has a TypeSafe key, or Jev is reachable through a gateway you already use (some community tools accept OpenRouter or Vercel AI Gateway keys; verify before relying on it), switch it on in P8 and add the Jev vs Haiku comparison to the scorecard.
- Keep `llm/jev_client.py` behind the same interface as the Haiku classifier so switching is one env var.

## What Jev is and is not

- **Is:** a fast, cheap, calibrated classifier over options we define. A classifier that cannot write text cannot hallucinate evidence, IDs or amounts. That property is why it fits Alibi.
- **Is not:** a chat model. It cannot run Claude Code, write code, explain, or make architecture decisions. TypeSafe documents arithmetic, dates and counting as unreliable, so those stay in our code (they already are).
- **Budget:** state plus all questions share roughly 32k tokens per request. Batch many questions per call over one state; do not make one call per question.

## Part A: Jev inside the product

| Use | Jev question type | State | Gate | Below gate |
|---|---|---|---|---|
| J1 Reason normalisation (replaces L3) | Choice over `ReasonCode` values + UNKNOWN | the raw reason string plus report context (column name, neighbouring fields) | 0.75 | Haiku with enum output; if still unsure, UNKNOWN -> SILENT |
| J2 Note label (replaces L4 label) | Choice: DEFECT_MENTIONED / NO_DEFECT_MENTIONED / IRRELEVANT / SUSPICIOUS_INSTRUCTION | the note, the check name and meaning | 0.75 | finding becomes NEUTRAL + flag, never SUPPORTS/CONTRADICTS |
| J3 Note evidence sentence (replaces L4 quote) | Choice over the note's sentences, split deterministically | same | 0.75 | no quote -> finding NEUTRAL |
| J4 Objection triage (W1) | Choice per candidate objection type: applies / does not apply | the claim packet summary (ids, windows, scopes) | 0.65 | send to deterministic verifier anyway (verifiers are the authority) |
| J5 Gap ranking (W2) | Score: how actionable is each gap for the owning Manager | gap descriptions | 0.65 | order by money only |

J3 is the elegant bit: because Jev picks one of our pre-split sentences, the "verbatim quote" requirement is satisfied by construction instead of by a validator.

All J1-J3 questions for a batch of charges go in one request per batch (one shared state per note or per report), which is the pattern TypeSafe recommends for cost and latency.

**The calibration story (use it in the pitch).** Jev returns a calibrated confidence per answer. Alibi turns low confidence into UNCERTAIN instead of a guess. That is "conservative decision-making" implemented with a measured number, not a prompt that says "be careful".

### Implementation

- `llm/jev_client.py`: `httpx` client, request builder (state + typed question map), response parser into Pydantic models, retries, timeouts, fail-open to the fallback path, response cache keyed by input hash (same table as LLM cache), `AuditEvent(stage="JEV")` with question ids, chosen option, probability, gate result.
- `JEV_ENABLED` flag. With it off, J1-J3 run on Haiku as specified in 06_LLM_LAYER.md.
- Cassettes for CI so tests do not need a key.

### Eval additions

- J1 on the 150 reason strings: accuracy of answers above gate, share escalated, and accuracy of escalated answers after fallback.
- J2/J3 on the 100 notes including 15 injections: injection detection must be 100% (an injection note must never yield SUPPORTS or CONTRADICTS).
- Report a small calibration table in the scorecard: accuracy by confidence bucket. Judges rarely see anyone measure calibration.
- Compare Jev vs Haiku on J1-J3: accuracy, p50 latency, cost per 1,000 decisions. Put the table on the Scorecard page.

## Part B: Jev in the Claude Code build workflow

Jev cannot be the model behind Claude Code. It sits at decision points around it.

### Install (every teammate)

```bash
# 1. Official TypeSafe skill: teaches Claude Code to write correct Jev code
claude plugin marketplace add typesafe-ai/skills
claude plugin install typesafe@typesafe-ai
# use it with: /typesafe:typesafe-ai   (or say "use the TypeSafe skill")

# 2. Key (TypeSafe account, free signup at typesafe.ai)
export TYPESAFE_API_KEY=...     # put in your shell profile, never in the repo
```

Restart Claude Code or run `/reload-plugins`.

### Optional boundary hooks (read each README first)

| Hook | What it does for this build | Why it helps us |
|---|---|---|
| `valentynkit/jev-belay` (Stop hook) | Reads the transcript before trusting a "done" claim | Directly targets the fake-completion failure mode in 15_CLAUDE_CODE_WORKFLOW.md |
| `shiftynick/jev-axi` (pre-tool gate) | Scores shell commands for destructiveness before they run | Safety while letting the agent run `make`, `docker`, `git` freely |
| `tamaratran/fast-jev-compaction` | Replaces compaction summaries with keep/drop judgments, keeps kept items verbatim | Long sessions keep exact error messages and file paths |

These community projects are days to weeks old. Install at most one or two, prefer ones that fail open, and uninstall immediately if a session behaves oddly. The official skill is the only first-party integration.

### What Jev must not do in the build

- Decide architecture, rules, or anything in docs/05. Humans and the docs decide those.
- Approve its own phase completion. The acceptance command output and the human review remain the gate; jev-belay is an extra check, not a replacement.
