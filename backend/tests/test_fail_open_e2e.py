"""Fail-open end to end (CLAUDE.md rule 5): a dependency fails partway through a run started
through POST /agent. The charge it hit is still stored as REVIEW with status pending and
reason DEPENDENCY_UNAVAILABLE, the rest of the run is decided normally, nothing is dropped,
and all of it is visible through GET /decisions and GET /decisions/{id}."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.agent import db_engine
from app.api.auth import configured_keys, hash_key, parse_api_keys
from app.core.config import REPO_ROOT
from app.main import app

ORG = "org_failopen_alpha"
KEY = "fail-open-test-key-0123456789"
PODS = ("receiving", "prep", "pack", "returns")
SAMPLE = REPO_ROOT / "data"


@pytest.fixture(scope="module")
def files(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The sample files with org_demo_alpha renamed, so no other test module sees them."""
    root = tmp_path_factory.mktemp("failopen")
    (root / "upstream").mkdir()

    def rename(src: Path, dst: Path) -> None:
        dst.write_text(
            src.read_text(encoding="utf-8").replace("org_demo_alpha", ORG), encoding="utf-8"
        )

    rename(SAMPLE / "fee_report_sample.csv", root / "report.csv")
    for pod in PODS:
        rename(SAMPLE / "upstream" / f"{pod}_sample.csv", root / "upstream" / f"{pod}_fo.csv")
    return root


@pytest.fixture
def client(app_engine: Engine, migrated_db: str) -> Iterator[TestClient]:
    app.dependency_overrides[db_engine] = lambda: app_engine
    app.dependency_overrides[configured_keys] = lambda: parse_api_keys(f"{ORG}:{hash_key(KEY)}")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_dependency_failure_mid_run_is_stored_as_pending_review_and_listed(
    client, files, monkeypatch
):
    import app.pipeline as pipeline

    real_decide = pipeline.decide
    calls: list[str] = []

    def decide_with_outage(charge, *args, **kwargs):
        # The third charge decided hits a database outage; every other one is real.
        calls.append(charge.line_id)
        if len(calls) == 3:
            raise sa.exc.OperationalError("SELECT 1", {}, Exception("connection lost"))
        return real_decide(charge, *args, **kwargs)

    monkeypatch.setattr("app.pipeline.decide", decide_with_outage)

    upload = [("report", ("report.csv", (files / "report.csv").read_bytes(), "text/csv"))]
    for pod in PODS:
        body = (files / "upstream" / f"{pod}_fo.csv").read_bytes()
        upload.append(("upstream", (f"{pod}_fo.csv", body, "text/csv")))
    posted = client.post("/agent", files=upload, headers={"X-API-Key": KEY})
    assert posted.status_code == 200, posted.text
    run_id = posted.headers["X-Alibi-Run-Id"]
    failed_line = calls[2]
    assert len(calls) > 3  # the run went on after the failure

    listed = client.get("/decisions", params={"run_id": run_id}, headers={"X-API-Key": KEY})
    assert listed.status_code == 200
    items = {i["line_id"]: i for i in listed.json()["items"]}
    # Nothing dropped: every charge the run saw has a stored, listed decision.
    assert set(items) == set(calls) == {d["subject"]["line_id"] for d in posted.json()}

    failed = items[failed_line]
    assert failed["decision"] == "REVIEW" and failed["status"] == "pending"
    assert failed["reason_code"] == "DEPENDENCY_UNAVAILABLE"
    assert failed["rule_id"] == "R_ENGINE_ERROR" and failed["confidence"] == "0.00"
    others = [i for line, i in items.items() if line != failed_line]
    assert others and all(i["status"] == "final" for i in others)
    assert not any(i["reason_code"] == "DEPENDENCY_UNAVAILABLE" for i in others)

    detail = client.get(f"/decisions/{failed['record_id']}", headers={"X-API-Key": KEY}).json()
    assert detail["record"]["status"] == "pending"
    assert "OperationalError" in detail["record"]["reason"]
    assert detail["charge"]["line_id"] == failed_line  # the input was persisted
    assert detail["integrity_problems"] == []
    # A pending charge cannot be claimed by a reviewer: its reimbursements were never computed.
    assert "pending" in detail["claim_refusal"]
