"""Evaluate the agent against the two humans' labels on the held-out set.

    make eval        (cd backend && uv run python ../eval/run_eval.py)

Refuses to run unless eval/labels_A.csv and eval/labels_B.csv exist, are committed to git
with no uncommitted changes, and label every case. Then:

1. raw agreement and Cohen's kappa between A and B, before any resolution;
2. gold labels: the shared label where A and B agree, else the committed row of
   eval/resolved_disagreements.csv. While any disagreement is unresolved no agent metric is
   computed: REPORT.md lists those cases and the run stops (exit 3);
3. the agent, through the real pipeline, on a freshly migrated eval database
   (EVAL_MIGRATION_DATABASE_URL / EVAL_DATABASE_URL), as of common.AS_OF;
4. eval/REPORT.md: claims, precision, false and missed claims, REVIEW rate, per charge type,
   latency, cost, failure modes and the per-case table.
"""

import csv
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text

from app.core.rules import load_engine_config, load_rules
from app.engine import ENGINE_VERSION
from app.ingest.loader import ingest_org
from app.models.decision import DecisionRecord
from app.pipeline import run_org
from common import (
    AS_OF,
    LABELS,
    LABELS_A,
    LABELS_B,
    REPO_ROOT,
    REPORT_CSV,
    REPORT_MD,
    RESOLVED_CSV,
    SHEET_CSV,
    UPSTREAM_DIR,
)
from metrics import (
    Agreement,
    Gold,
    LabelError,
    Score,
    agreement,
    build_gold,
    percentile,
    read_labels,
    read_resolutions,
    score,
)

ORGS = ("org_demo_alpha", "org_demo_bravo")
BACKEND = REPO_ROOT / "backend"
EXIT_REFUSED, EXIT_UNRESOLVED = 2, 3


class EvalRefused(RuntimeError):
    """The eval must not run in this state. The message says why."""


# --- guards ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(repo), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )


def require_committed(paths: list[Path], repo: Path = REPO_ROOT) -> str:
    """Refuse unless every path exists, is tracked by git and has no staged or unstaged
    change against HEAD. Returns HEAD's commit id."""
    for p in paths:
        if not p.is_file():
            raise EvalRefused(f"{p.name} is missing: both labellers must finish first")
        rel = str(p.resolve().relative_to(repo.resolve()))
        if _git(repo, "ls-files", "--error-unmatch", rel).returncode != 0:
            raise EvalRefused(f"{p.name} is not committed to git; commit it before the eval")
        if _git(repo, "diff", "--quiet", "HEAD", "--", rel).returncode != 0:
            raise EvalRefused(f"{p.name} has uncommitted changes; commit them before the eval")
    head = _git(repo, "rev-parse", "HEAD")
    if head.returncode != 0:
        raise EvalRefused("cannot read the git commit")
    return head.stdout.strip()


def sheet_case_ids(path: Path = SHEET_CSV) -> list[str]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [row["case_id"] for row in csv.DictReader(fh)]


def reasons(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {r["case_id"]: (r.get("reason") or "").strip() for r in csv.DictReader(fh)}


# --- the agent run --------------------------------------------------------------------


def _require_eval_db(url: str) -> None:
    name = make_url(url).database or ""
    if "eval" not in name and "test" not in name:
        raise EvalRefused(
            f"refusing to reset database {name!r}: the eval database name must contain "
            "'eval' (or 'test' in tests)"
        )


def prepare_database(migration_url: str) -> None:
    """Drop and recreate the public schema, then migrate to head as the owner role, so the
    eval database holds nothing but the eval set."""
    _require_eval_db(migration_url)
    owner = create_engine(migration_url, isolation_level="AUTOCOMMIT")
    with owner.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public AUTHORIZATION alibi_owner"))
        conn.execute(text("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO alibi_app"))
    owner.dispose()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", migration_url.replace("%", "%%"))
    command.upgrade(cfg, "head")


@dataclass
class AgentRun:
    decisions: dict[str, DecisionRecord]
    latency_ms: dict[str, float]
    ingest_s: float
    total_s: float


def run_agent(
    app_url: str,
    migration_url: str,
    report: Path = REPORT_CSV,
    upstream: Path = UPSTREAM_DIR,
    orgs: tuple[str, ...] = ORGS,
) -> AgentRun:
    """Ingest the eval files and decide every line, per org, through the real pipeline."""
    _require_eval_db(app_url)
    prepare_database(migration_url)
    secret = os.environ.get("ATTACHMENT_KEY_SECRET", "eval-attachment-secret")
    engine = create_engine(app_url)
    decisions: dict[str, DecisionRecord] = {}
    latency: dict[str, float] = {}
    started = time.perf_counter()
    ingest_s = 0.0
    try:
        for org in orgs:
            t0 = time.perf_counter()
            ingest_org(engine, org, report, upstream, secret)
            ingest_s += time.perf_counter() - t0
            result = run_org(engine, org, AS_OF)
            for d in result.decisions:
                decisions[d.subject.line_id] = d
            latency.update(result.latency_ms)
    finally:
        engine.dispose()
    return AgentRun(decisions, latency, ingest_s, time.perf_counter() - started)


# --- report ---------------------------------------------------------------------------


def _pct(x: object) -> str:
    return "n/a" if x is None else f"{x}"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    def cell(v: str) -> str:
        return v.replace("|", "\\|").replace("\n", " ")

    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]
    return out


@dataclass(frozen=True)
class Labels:
    a: dict[str, str]
    b: dict[str, str]
    reason_a: dict[str, str]
    reason_b: dict[str, str]


def agreement_section(ag: Agreement, lab: Labels) -> list[str]:
    lines = [
        "## 1. Agreement between the two labellers (before any resolution)",
        "",
        f"- Cases labelled by both: **{ag.n}**",
        f"- Raw agreement: **{ag.agreed} of {ag.n} = {ag.raw}**",
        f"- Cohen's kappa: **{_pct(ag.kappa)}** (chance agreement p_e = {ag.expected})",
        "",
        "A (rows) against B (columns):",
        "",
    ]
    lines += _table(
        ["A \\ B", *LABELS],
        [[a, *(str(ag.confusion.get((a, b), 0)) for b in LABELS)] for a in LABELS],
    )
    lines += ["", f"Disagreements ({len(ag.disagreements)}):", ""]
    if ag.disagreements:
        lines += _table(
            ["case", "A", "A's reason", "B", "B's reason"],
            [
                [c, lab.a[c], lab.reason_a.get(c, ""), lab.b[c], lab.reason_b.get(c, "")]
                for c in ag.disagreements
            ],
        )
    else:
        lines.append("none")
    return [*lines, ""]


def _score_rows(scores: dict[str, Score]) -> list[list[str]]:
    rows = []
    for name, s in scores.items():
        rows.append(
            [
                name,
                str(s.n),
                str(s.claims_recommended),
                str(s.correct_claims),
                str(s.false_claims),
                str(s.missed_claims),
                _pct(s.claim_precision),
                _pct(s.review_rate),
                _pct(s.accuracy),
            ]
        )
    return rows


def _note(d: DecisionRecord) -> str:
    code = f" [{d.reason_code.value}]" if d.reason_code else ""
    pending = " status pending" if d.status.value == "pending" else ""
    return f"{d.rule_id}{code}{pending}"


def render_report(
    *,
    commit: str,
    ag: Agreement,
    gold: Gold,
    lab: Labels,
    run: AgentRun | None,
    charge_types: dict[str, str],
) -> str:
    a, b = lab.a, lab.b
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out = [
        "# Evaluation report",
        "",
        f"Generated {now} by `eval/run_eval.py` at commit `{commit[:12]}`. "
        f"Decisions judged as of {AS_OF}. Engine `rules@{ENGINE_VERSION}`, "
        f"rules `{load_rules().rules_hash[:12]}`, engine config "
        f"`{load_engine_config().config_hash[:12]}`.",
        "",
        "Held-out set: `eval/data/` (see `eval/README.md`). Labels: `eval/labels_A.csv` and "
        "`eval/labels_B.csv`, committed before the agent ran. Definitions are at the end.",
        "",
        *agreement_section(ag, lab),
        "## 2. Gold labels",
        "",
    ]
    if gold.unresolved:
        out += [
            f"**Agent metrics not computed: {len(gold.unresolved)} disagreement(s) are "
            "unresolved.** Resolve each in `eval/resolved_disagreements.csv` "
            "(`case_id,gold_label,note`), commit it, and run `make eval` again.",
            "",
            "Unresolved: " + ", ".join(gold.unresolved),
            "",
        ]
        return "\n".join(out)
    dist = Counter(gold.labels.values())
    out += [
        f"{len(gold.labels)} cases: "
        + ", ".join(f"{k} {dist.get(k, 0)}" for k in LABELS)
        + f". {len(gold.labels) - len(gold.notes)} agreed by both labellers, "
        f"{len(gold.notes)} resolved after discussion.",
        "",
    ]
    if gold.notes:
        out += _table(
            ["case", "A", "B", "gold", "resolution note"],
            [[c, a[c], b[c], gold.labels[c], n] for c, n in sorted(gold.notes.items())],
        )
        out.append("")
    assert run is not None
    agent = {c: d.decision.value for c, d in run.decisions.items()}
    overall = score(gold.labels, agent)
    by_type: dict[str, Score] = {"all": overall}
    for ct in sorted(set(charge_types.values())):
        cases = {c: g for c, g in gold.labels.items() if charge_types[c] == ct}
        by_type[ct] = score(cases, agent)
    header = [
        "charge type",
        "N",
        "claims recommended",
        "correct claims",
        "false claims",
        "missed claims",
        "claim precision",
        "REVIEW rate",
        "agreement with gold",
    ]
    out += [
        "## 3. Agent results",
        "",
        f"- Charges evaluated: **{overall.n}**",
        f"- Claims recommended: **{overall.claims_recommended}**; correct claims: "
        f"**{overall.correct_claims}**; false claims: **{overall.false_claims}**; missed "
        f"claims: **{overall.missed_claims}** (gold has {overall.gold_claims} CLAIM)",
        f"- Claim precision: **{_pct(overall.claim_precision)}** "
        f"({overall.correct_claims} of {overall.claims_recommended})",
        f"- REVIEW rate: **{_pct(overall.review_rate)}** ({overall.review} of {overall.n}); "
        f"gold REVIEW rate {Counter(gold.labels.values())['REVIEW']} of {overall.n}",
        f"- Agreement with gold on all three outcomes: {_pct(overall.accuracy)}",
        "",
        *_table(header, _score_rows(by_type)),
        "",
        "Gold (rows) against agent (columns):",
        "",
        *_table(
            ["gold \\ agent", *LABELS],
            [[g, *(str(overall.by_pair.get((g, d), 0)) for d in LABELS)] for g in LABELS],
        ),
        "",
    ]
    # Failure modes: every disagreement with gold, false claims first.
    wrong = [c for c in sorted(gold.labels) if gold.labels[c] != agent[c]]
    order = {"CLAIM": 0, "REVIEW": 1, "DO_NOT_CLAIM": 2}
    wrong.sort(key=lambda c: (order[agent[c]], gold.labels[c], c))
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for c in wrong:
        groups[(gold.labels[c], agent[c], run.decisions[c].rule_id)].append(c)
    out += ["## 4. Failure modes", ""]
    if not wrong:
        out += ["The agent agreed with gold on every case.", ""]
    else:
        out += _table(
            ["gold", "agent", "rule that fired", "cases", "count"],
            [[g, d, r, ", ".join(cs), str(len(cs))] for (g, d, r), cs in groups.items()],
        )
        out += ["", "Reasons given by the agent on each disagreement:", ""]
        out += _table(
            ["case", "gold", "agent", "agent reason"],
            [[c, gold.labels[c], agent[c], run.decisions[c].reason] for c in wrong],
        )
        out.append("")
    lat = list(run.latency_ms.values())
    pending = sum(1 for d in run.decisions.values() if d.status.value == "pending")
    model_calls = sum(1 for d in run.decisions.values() if d.model_version is not None)
    llm = os.environ.get("LLM_ENABLED", "false")
    out += [
        "## 5. Latency and cost",
        "",
        f"- Per charge (decide, validate citations against Postgres, persist): mean "
        f"{sum(lat) / len(lat):.1f} ms, p50 {percentile(lat, 50):.1f} ms, p95 "
        f"{percentile(lat, 95):.1f} ms, max {max(lat):.1f} ms, over {len(lat)} charges.",
        f"- Whole run including ingestion and migration: {run.total_s:.2f} s "
        f"(ingestion {run.ingest_s:.2f} s), {run.total_s * 1000 / len(lat):.1f} ms per charge.",
        f"- Model calls: {model_calls} (LLM_ENABLED={llm}); model cost per charge: $0.00. "
        "Decisions carry no model version.",
        f"- Decisions that failed open (status pending): {pending}.",
        "",
        "## 6. Every case",
        "",
    ]
    out += _table(
        ["case", "charge type", "A", "B", "gold", "agent", "agent vs gold", "notes"],
        [
            [
                c,
                charge_types[c],
                a[c],
                b[c],
                gold.labels[c],
                agent[c],
                "agree" if agent[c] == gold.labels[c] else "disagree",
                _note(run.decisions[c]),
            ]
            for c in sorted(gold.labels)
        ],
    )
    out += [
        "",
        "## Definitions",
        "",
        "- Correct claim: agent CLAIM and gold CLAIM. False claim: agent CLAIM, gold "
        "DO_NOT_CLAIM or REVIEW. Missed claim: gold CLAIM, agent DO_NOT_CLAIM or REVIEW.",
        "- Claim precision = correct claims / claims recommended (n/a with no claims).",
        "- REVIEW rate = agent REVIEW / charges evaluated.",
        "- Cohen's kappa = (p_o - p_e) / (1 - p_e) over the three labels, computed on the "
        "labellers' own labels before any resolution.",
        "- Routing confidence on decisions is not used here; it is not a probability of being "
        "right (ARCHITECTURE.md).",
        "",
    ]
    return "\n".join(out)


def charge_types_of(report: Path = REPORT_CSV) -> dict[str, str]:
    with report.open(newline="", encoding="utf-8") as fh:
        return {r["line_id"]: r["charge_type"] for r in csv.DictReader(fh)}


def main() -> int:
    try:
        commit = require_committed([LABELS_A, LABELS_B], REPO_ROOT)
        ids = sheet_case_ids(SHEET_CSV)
        a, b = read_labels(LABELS_A, ids), read_labels(LABELS_B, ids)
        ag = agreement(a, b)
        if RESOLVED_CSV.exists():
            require_committed([RESOLVED_CSV], REPO_ROOT)
        gold = build_gold(a, b, read_resolutions(RESOLVED_CSV, ag.disagreements))
    except (EvalRefused, LabelError) as exc:
        print(f"eval refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    lab = Labels(a, b, reasons(LABELS_A), reasons(LABELS_B))
    types = charge_types_of()
    print(f"agreement: {ag.agreed}/{ag.n} = {ag.raw}, Cohen's kappa {_pct(ag.kappa)}")
    if gold.unresolved:
        REPORT_MD.write_text(
            render_report(commit=commit, ag=ag, gold=gold, lab=lab, run=None, charge_types=types),
            encoding="utf-8",
        )
        print(
            f"{len(gold.unresolved)} disagreement(s) unresolved; no agent metrics computed: "
            + ", ".join(gold.unresolved),
            file=sys.stderr,
        )
        return EXIT_UNRESOLVED
    try:
        app_url = os.environ["EVAL_DATABASE_URL"]
        migration_url = os.environ["EVAL_MIGRATION_DATABASE_URL"]
        run = run_agent(app_url, migration_url)
    except KeyError as exc:
        print(f"eval refused: {exc.args[0]} is not set (see Makefile)", file=sys.stderr)
        return EXIT_REFUSED
    except EvalRefused as exc:
        print(f"eval refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    REPORT_MD.write_text(
        render_report(commit=commit, ag=ag, gold=gold, lab=lab, run=run, charge_types=types),
        encoding="utf-8",
    )
    print(f"wrote {REPORT_MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
