# Round 2 plan (overrides schedules and deliverables in docs/archive/pre-round2-design/)

## Source of truth
The Round 2 rules were published in open PRs #1-#6 on the organiser repo (individual build, fork workflow, deadline 1 Oct 2026 18:00 IST). Confirmation requested in issue #15. Until an organiser says otherwise, this plan follows those rules.

## Deliverables (all required)
1. Fork containing the complete implementation (commits during build phase only)
2. README.md: problem understanding, solution overview, setup, usage, architecture summary, assumptions, limitations, evaluation approach
3. ARCHITECTURE.md: components, data flow, evidence flow, model usage, decision logic, engineering decisions
4. Working agent (CLI + POST /agent + review UI)
5. Evaluation results: method, held-out set, claim precision, review rate, false claims, missed claims, failure modes, latency, cost
6. Demo video
7. Deployment URL
8. LinkedIn post tagging CodeQuesters and Sydon.AI (mandatory)
9. Submission form (opens 27 Sep, closes 1 Oct 18:00 IST, no resubmission)

## Rubric (100)
Problem understanding 15 · Agent functionality and decision quality 25 · Evaluation, accuracy and uncertainty 25 · Evidence, traceability and engineering 20 · UX, demo and docs 15.

## Schedule (IST)

| Day | Date | Build | Done when |
|---|---|---|---|
| 1 | Fri 25 Sep | Restructure fork. Scaffold (P0), models mapped to official contract, CSV-to-contract adapter, Postgres RLS + isolation test (P1) | Isolation test green; adapter loads all sample files |
| 2 | Sat 26 Sep | Pre-checks, unit resolution, evidence retrieval, rule engine, claims + citation validator (P4-P7). Headless CLI end to end | CLI prints a decision for every sample line with evidence and reason |
| 3 | Sun 27 Sep | Held-out eval set built and labelled by two humans BEFORE running the agent. Eval harness, precision report (P11). POST /agent, GET /health (P9) | First honest precision number with failure modes |
| 4 | Mon 28 Sep | Review UI: charges table, decision detail with evidence trail, override flow (P10). Fail-open tests | Operator can review, override with reason, see history |
| 5 | Tue 29 Sep | LLM layer (notes classification + explanations, batched, validated), agent chat if time. Deploy (P12) | Live URL; LLM off still works |
| 6 | Wed 30 Sep | Final eval run, README, ARCHITECTURE, eval report, demo video | All docs complete; video recorded |
| 7 | Thu 1 Oct | LinkedIn post, link checks, submit by 14:00 IST (4 hours buffer) | Form submitted |

Weekly Claude usage resets Tue 29 Sep 20:30 IST. Plan heavy generation for Fri-Sat on cloud credit.

## Scope decisions
- Keep: rule engine, citation validator, content hashes, append-only audit, RLS, overrides, fail-open, REVIEW prominence, held-out human-labelled eval.
- Stretch only if Day 5 ends on time: Glass Box live trace, cross-examination agent, evidence gap summary.
- Dropped for Round 2: cross-pod contract negotiation (organisers provide the contract), faces/customer letter as deliverables (kept in docs/product/ as problem-understanding material), Jev, PDF ingestion.

## Known findings to carry into README "Assumptions and limitations"
42 of 61 sample lines are weight-tier fees with no upstream weight data (will be REVIEW / INSUFFICIENT); unit_id granularity differs between receiving and fee report; lost_inbound at 0.00; supplier shortfall is not channel loss; returns records exist for FBA units; 9 units have no outbound record.
