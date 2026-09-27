"""Command line entry point.

`alibi ingest` loads the report and upstream CSVs for one organisation.
`alibi run` ingests (idempotent), decides every charge of that organisation, persists the
decisions and prints each one with its evidence and reason.
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer

from app.api.auth import hash_key, new_key
from app.core.config import SettingsError, get_settings
from app.core.rules import load_rules
from app.db.session import get_engine
from app.engine import DECIDED_BY
from app.ingest.loader import ingest_org
from app.pipeline import run_org
from app.report import render_decision, render_summary, rules_status

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def _root() -> None:
    """Alibi: Recovery Manager."""


@app.command()
def ingest(
    report: Annotated[Path, typer.Option(help="Fee/adjustment/reimbursement report CSV")],
    upstream: Annotated[Path, typer.Option(help="Directory with the upstream pod CSVs")],
    org: Annotated[str, typer.Option(help="Organisation to load, e.g. org_demo_alpha")],
) -> None:
    """Load charges and upstream evidence for one organisation. Idempotent."""
    secret = get_settings().attachment_key_secret.get_secret_value()
    s = ingest_org(get_engine(), org, report, upstream, secret)
    typer.echo(f"org: {s.org}")
    typer.echo(f"charges:    {s.charges_inserted} inserted of {s.charges_total}")
    for pod, (ins, total) in s.records.items():
        typer.echo(f"{pod + ':':<12}{ins} inserted of {total}")
    typer.echo(f"quarantined: {s.quarantined}")
    typer.echo(f"rows for other orgs skipped: {s.skipped_other_org}")
    typer.echo(
        f"in db for {s.org}: charges={s.db_charges} evidence_records={s.db_records} "
        f"attachments={s.db_attachments}"
    )


@app.command()
def run(
    report: Annotated[Path, typer.Option(help="Fee/adjustment/reimbursement report CSV")],
    upstream: Annotated[Path, typer.Option(help="Directory with the upstream pod CSVs")],
    org: Annotated[str, typer.Option(help="Organisation to decide, e.g. org_demo_alpha")],
    as_of: Annotated[
        str | None, typer.Option(help="Date filing windows are judged at (YYYY-MM-DD)")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print decision records as JSON")] = False,
) -> None:
    """Ingest, decide every charge for one organisation, persist and print the decisions."""
    try:
        when = date.fromisoformat(as_of) if as_of else datetime.now(UTC).date()
    except ValueError as exc:
        raise typer.BadParameter("expected a date as YYYY-MM-DD", param_hint="--as-of") from exc
    secret = get_settings().attachment_key_secret.get_secret_value()
    engine = get_engine()
    ingest_org(engine, org, report, upstream, secret)
    result = run_org(engine, org, when)
    if as_json:
        typer.echo(json.dumps([d.model_dump(mode="json") for d in result.decisions], indent=2))
        return
    typer.echo(f"alibi run  org {org}  run {result.run_id}  as of {when}  decided by {DECIDED_BY}")
    typer.echo(rules_status(load_rules()))
    typer.echo("")
    for d in result.decisions:
        for line in render_decision(d):
            typer.echo(line)
        typer.echo("")
    for line in render_summary(result.decisions):
        typer.echo(line)


@app.command("llm-smoke")
def llm_smoke(
    org: Annotated[str, typer.Option(help="Organisation whose newest run to use")] = (
        "org_demo_alpha"
    ),
    line: Annotated[
        str | None, typer.Option(help="Charge line to explain (default: a CLAIM, else the first)")
    ] = None,
    record: Annotated[
        Path | None, typer.Option(help="Save the raw response as a test fixture (JSON)")
    ] = None,
) -> None:
    """Send one real decision trace to the configured model (whatever LLM_ENABLED says) and
    print the validated explanation, latency, tokens and cost. Exit 0: the model's text was
    used. Exit 3: it fell back to the template. Exit 2: settings or data missing. Nothing
    is written to the database."""
    from app.db import repo
    from app.db.session import org_session
    from app.llm.config import LLMConfigError, llm_config
    from app.llm.explain import Explainer
    from app.llm.vertex import VertexProvider

    s = get_settings()
    try:
        cfg = llm_config(s.model_copy(update={"llm_enabled": True}))
    except LLMConfigError as exc:
        typer.echo(f"llm-smoke: {exc}", err=True)
        raise typer.Exit(2) from None
    with org_session(get_engine(), org) as session:
        runs = repo.list_runs(session)
        decisions = repo.list_decisions(session, runs[0].run_id) if runs else []
    if line:
        decisions = [d for d in decisions if d.subject.line_id == line]
    if not decisions:
        where = f"line {line} in " if line else ""
        typer.echo(f"llm-smoke: no decision for {where}{org}; run `make demo` first", err=True)
        raise typer.Exit(2)
    # Default: a CLAIM if the run has one (the richest trace), else the first decision.
    d = decisions[0] if line else next((x for x in decisions if x.claim), decisions[0])

    provider = VertexProvider(cfg)
    creds = str(cfg.credentials_file) if cfg.credentials_file else "Application Default Credentials"
    typer.echo(f"provider  vertex  project {cfg.project}  location {cfg.location}")
    typer.echo(f"model     {cfg.model}  (timeout {cfg.timeout_s}s, one attempt)")
    typer.echo(f"auth      {creds}")
    typer.echo(f"decision  {d.subject.line_id}  {d.decision.value}  {d.rule_id}  (run {d.run_id})")
    typer.echo("")
    x = Explainer(provider=provider, cfg=cfg).explanation_for(None, d)  # no cache: a real call

    if record is not None and provider.last_response is not None:
        dump = provider.last_response.model_dump(mode="json", exclude_none=True)
        record.write_text(
            json.dumps(
                {
                    "_about": f"recorded by make llm-smoke on {datetime.now(UTC).date()} "
                    f"({cfg.model}, {d.subject.line_id})",
                    "response": dump,
                },
                indent=2,
            )
            + "\n"
        )
        typer.echo(f"recorded  {record}")

    if x.cost_estimate_usd is not None:
        cost = f"{x.cost_estimate_usd} USD (estimate)"
    else:
        cost = x.cost_note or "- (no call completed)"
    typer.echo(f"served by {x.model_id or 'no response'}")
    typer.echo(f"latency   {x.latency_ms if x.latency_ms is not None else '-'} ms")
    typer.echo(
        f"tokens    in {x.input_tokens if x.input_tokens is not None else '-'}  "
        f"out {x.output_tokens if x.output_tokens is not None else '-'} (incl. thinking)"
    )
    typer.echo(f"cost      {cost}")
    typer.echo("")
    if x.source == "model":
        typer.echo("MODEL EXPLANATION USED (validated against the decision trace):")
        typer.echo(x.text)
        return
    typer.echo(f"FELL BACK TO TEMPLATE: {x.fallback_reason}")
    typer.echo(x.text)
    raise typer.Exit(3)


@app.command("api-key")
def api_key(
    org: Annotated[str, typer.Option(help="Organisation the new key acts for")],
) -> None:
    """Make a new API key for POST /agent. Prints the key once and the ALIBI_API_KEYS entry
    (its hash) to add to .env; the key itself is never stored."""
    key = new_key()
    typer.echo(f"key (give to the client, shown once): {key}")
    typer.echo(f"add to ALIBI_API_KEYS in .env:       {org}:{hash_key(key)}")


def main() -> None:
    """Console entry point: configuration errors print one line instead of a traceback."""
    try:
        app()
    except SettingsError as exc:
        typer.echo(f"alibi: {exc}", err=True)
        raise SystemExit(2) from None
