"""Command line entry point. `alibi ingest` loads the sample CSVs for one organisation."""

from pathlib import Path
from typing import Annotated

import typer

from app.core.config import get_settings
from app.db.session import get_engine
from app.ingest.loader import ingest_org

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
