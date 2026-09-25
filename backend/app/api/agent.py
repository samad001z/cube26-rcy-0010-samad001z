"""POST /agent: a report and the upstream CSVs in, one decision per charge out, in the same
JSON shape as `alibi run --json`.

The organisation comes only from the API key (app.api.auth). Nothing in the request can
name another one: the endpoint declares no organisation field, and ingestion loads only the
key's organisation's rows (rows for any other organisation are skipped and counted in the
X-Alibi-Rows-Skipped-Other-Org header). Every read and write runs in a session scoped to
that organisation, so row-level security applies.
"""

import re
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import require_org
from app.core.config import get_settings
from app.db.session import get_engine
from app.ingest.loader import PODS, ingest_org
from app.pipeline import run_org

router = APIRouter()

MAX_FILE_BYTES = 10 * 1024 * 1024
_UPSTREAM_NAME = re.compile(rf"^({'|'.join(PODS)})_[A-Za-z0-9_.-]*\.csv$")


def db_engine() -> Engine:
    return get_engine()


def _save(upload: UploadFile, target: Path) -> None:
    data = upload.file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"{upload.filename} is larger than {MAX_FILE_BYTES} bytes",
        )
    target.write_bytes(data)


def _upstream_name(upload: UploadFile) -> str:
    name = Path(upload.filename or "").name
    if name != (upload.filename or "") or not _UPSTREAM_NAME.match(name):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"upstream file {upload.filename!r} must be named <pod>_<anything>.csv, "
            f"pod one of {', '.join(PODS)}",
        )
    return name


@router.post("/agent")
def post_agent(
    org: Annotated[str, Depends(require_org)],
    engine: Annotated[Engine, Depends(db_engine)],
    report: Annotated[UploadFile, File(description="fee, adjustment or reimbursement CSV")],
    upstream: Annotated[
        list[UploadFile], File(description="one CSV per pod: receiving_, prep_, pack_, returns_")
    ],
    as_of: Annotated[str | None, Form(description="YYYY-MM-DD; default today (UTC)")] = None,
) -> JSONResponse:
    try:
        when = date.fromisoformat(as_of) if as_of else datetime.now(UTC).date()
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "as_of must be YYYY-MM-DD"
        ) from None
    names = [_upstream_name(u) for u in upstream]
    pods = [n.split("_", 1)[0] for n in names]
    if sorted(pods) != sorted(PODS):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"send exactly one upstream file per pod ({', '.join(PODS)}); got {sorted(pods)}",
        )
    secret = get_settings().attachment_key_secret.get_secret_value()
    with tempfile.TemporaryDirectory(prefix="alibi-agent-") as tmp:
        root = Path(tmp)
        (root / "upstream").mkdir()
        _save(report, root / "report.csv")
        for u, name in zip(upstream, names, strict=True):
            _save(u, root / "upstream" / name)
        try:
            try:
                summary = ingest_org(engine, org, root / "report.csv", root / "upstream", secret)
            except (KeyError, ValueError, UnicodeDecodeError) as exc:
                # Malformed files (bad header, not UTF-8). Bad rows are quarantined instead.
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, f"could not read the files: {exc}"
                ) from None
            # Each charge fails open inside run_org; only a whole-run failure reaches here.
            result = run_org(engine, org, when)
        except SQLAlchemyError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"dependency unavailable: {type(exc).__name__}",
            ) from None
    return JSONResponse(
        content=[d.model_dump(mode="json") for d in result.decisions],
        headers={
            "X-Alibi-Run-Id": result.run_id,
            "X-Alibi-Organization": org,
            "X-Alibi-Rows-Skipped-Other-Org": str(summary.skipped_other_org),
            "X-Alibi-Rows-Quarantined": str(summary.quarantined),
        },
    )
