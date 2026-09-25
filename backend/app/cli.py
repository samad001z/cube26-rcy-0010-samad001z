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

from app.core.config import get_settings
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
    when = date.fromisoformat(as_of) if as_of else datetime.now(UTC).date()
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
