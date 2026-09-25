"""POST /agent: API-key auth, organisation taken only from the key, tenancy isolation, and
the same JSON shape as `alibi run --json`. Runs on Postgres with row-level security."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.agent import db_engine
from app.api.auth import configured_keys, hash_key, org_for_key, parse_api_keys
from app.core.config import REPO_ROOT, get_settings
from app.core.rules import parse_engine_config
from app.db import tables as t
from app.db.session import org_session
from app.main import app
from app.models.decision import DecisionRecord

ALPHA, BRAVO = "org_api_alpha", "org_api_bravo"
ALPHA_KEY, BRAVO_KEY = "alpha-test-key-0123456789", "bravo-test-key-9876543210"
PODS = ("receiving", "prep", "pack", "returns")
SAMPLE = REPO_ROOT / "data"


@pytest.fixture(scope="module")
def files(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The sample files with their two orgs renamed, so these tests never touch the orgs
    the other test modules check."""
    root = tmp_path_factory.mktemp("api")
    (root / "upstream").mkdir()

    def rename(src: Path, dst: Path) -> None:
        text = src.read_text(encoding="utf-8")
        dst.write_text(
            text.replace("org_demo_alpha", ALPHA).replace("org_demo_bravo", BRAVO),
            encoding="utf-8",
        )

    rename(SAMPLE / "fee_report_sample.csv", root / "report.csv")
    for pod in PODS:
        rename(SAMPLE / "upstream" / f"{pod}_sample.csv", root / "upstream" / f"{pod}_api.csv")
    return root


@pytest.fixture
def client(app_engine: Engine, migrated_db: str) -> Iterator[TestClient]:
    keys = f"{ALPHA}:{hash_key(ALPHA_KEY)},{BRAVO}:{hash_key(BRAVO_KEY)}"
    app.dependency_overrides[db_engine] = lambda: app_engine
    app.dependency_overrides[configured_keys] = lambda: parse_api_keys(keys)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _post(
    client: TestClient,
    files: Path,
    key: str | None,
    data: dict[str, str] | None = None,
    upstream_names: dict[str, str] | None = None,
):
    names = upstream_names or {p: f"{p}_api.csv" for p in PODS}
    upload = [("report", ("report.csv", (files / "report.csv").read_bytes(), "text/csv"))]
    for pod, name in names.items():
        body = (files / "upstream" / f"{pod}_api.csv").read_bytes()
        upload.append(("upstream", (name, body, "text/csv")))
    headers = {"X-API-Key": key} if key is not None else {}
    return client.post("/agent", files=upload, data=data or {}, headers=headers)


def _rows(engine: Engine, org: str, table: sa.Table) -> int:
    with org_session(engine, org) as s:
        return s.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()


def _sample_lines(org: str) -> int:
    rows = (SAMPLE / "fee_report_sample.csv").read_text().splitlines()[1:]
    return sum(1 for r in rows if f",{org}," in r)


# --- authentication -------------------------------------------------------------------


@pytest.mark.parametrize("key", [None, "", "wrong-key", ALPHA_KEY + "x", hash_key(ALPHA_KEY)])
def test_missing_or_wrong_key_is_401(client, files, key):
    resp = _post(client, files, key)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "ApiKey"
    assert resp.json() == {"detail": "missing or invalid API key"}


def test_a_401_happens_before_any_row_is_written(client, files, app_engine):
    before = {org: _rows(app_engine, org, t.charges) for org in (ALPHA, BRAVO)}
    assert _post(client, files, "wrong-key").status_code == 401
    assert {org: _rows(app_engine, org, t.charges) for org in (ALPHA, BRAVO)} == before


def test_key_in_the_query_string_is_not_accepted(client, files):
    upload = [("report", ("report.csv", (files / "report.csv").read_bytes(), "text/csv"))]
    resp = client.post(f"/agent?X-API-Key={ALPHA_KEY}", files=upload)
    assert resp.status_code == 401


def test_no_configured_keys_means_every_request_is_401(client, files):
    app.dependency_overrides[configured_keys] = lambda: parse_api_keys("")
    assert _post(client, files, ALPHA_KEY).status_code == 401


# --- tenancy --------------------------------------------------------------------------


def test_alpha_key_decides_only_alpha_and_writes_nothing_for_bravo(client, files, app_engine):
    bravo_before = {tb.name: _rows(app_engine, BRAVO, tb) for tb in (t.charges, t.decisions)}
    resp = _post(client, files, ALPHA_KEY)
    assert resp.status_code == 200, resp.text
    decisions = [DecisionRecord.model_validate(d) for d in resp.json()]
    assert len(decisions) == _sample_lines("org_demo_alpha") == 40
    assert {d.organization_id for d in decisions} == {ALPHA}
    assert resp.headers["x-alibi-organization"] == ALPHA
    assert int(resp.headers["x-alibi-rows-skipped-other-org"]) > 0  # bravo rows skipped
    # Nothing was written under bravo by alpha's request.
    assert {tb.name: _rows(app_engine, BRAVO, tb) for tb in (t.charges, t.decisions)} == (
        bravo_before
    )
    assert _rows(app_engine, ALPHA, t.charges) == 40


def test_organization_id_in_the_request_body_is_ignored(client, files, app_engine):
    bravo_before = _rows(app_engine, BRAVO, t.decisions)
    resp = _post(client, files, ALPHA_KEY, data={"organization_id": BRAVO, "org": BRAVO})
    assert resp.status_code == 200
    assert {d["organization_id"] for d in resp.json()} == {ALPHA}
    assert _rows(app_engine, BRAVO, t.decisions) == bravo_before


def test_bravo_key_sees_none_of_alphas_data(client, files, app_engine):
    alpha_resp = _post(client, files, ALPHA_KEY)
    alpha_lines = {d["subject"]["line_id"] for d in alpha_resp.json()}
    resp = _post(client, files, BRAVO_KEY)
    assert resp.status_code == 200
    decisions = resp.json()
    assert len(decisions) == _sample_lines("org_demo_bravo") == 21
    assert {d["organization_id"] for d in decisions} == {BRAVO}
    assert not ({d["subject"]["line_id"] for d in decisions} & alpha_lines)
    # Bravo's decisions cite only bravo records: every cited id was read under bravo's RLS.
    with org_session(app_engine, BRAVO) as s:
        bravo_ids = set(s.execute(sa.select(t.evidence_records.c.record_id)).scalars())
        alpha_decision_ids = {d["record_id"] for d in alpha_resp.json()}
        visible: set[str] = set(s.execute(sa.select(t.decisions.c.record_id)).scalars())
    for d in decisions:
        for c in d["citations"]:
            if c["kind"] == "evidence":
                assert c["id"] in bravo_ids
    assert not (visible & alpha_decision_ids)


def test_response_has_the_cli_json_shape_and_every_decision_verifies(client, files):
    resp = _post(client, files, ALPHA_KEY)
    body = resp.json()
    assert isinstance(body, list) and body
    for raw in body:
        d = DecisionRecord.model_validate(raw)
        assert d.verify_hash()
        assert raw == d.model_dump(mode="json")  # exactly what `alibi run --json` prints


# --- input validation -----------------------------------------------------------------


def test_upstream_files_must_be_one_per_pod_with_a_pod_prefix(client, files):
    bad_name = {**{p: f"{p}_api.csv" for p in PODS}, "prep": "evidence.csv"}
    assert _post(client, files, ALPHA_KEY, upstream_names=bad_name).status_code == 422
    traversal = {**{p: f"{p}_api.csv" for p in PODS}, "prep": "../prep_x.csv"}
    assert _post(client, files, ALPHA_KEY, upstream_names=traversal).status_code == 422
    missing = {p: f"{p}_api.csv" for p in PODS if p != "returns"}
    resp = _post(client, files, ALPHA_KEY, upstream_names=missing)
    assert resp.status_code == 422 and "one upstream file per pod" in resp.json()["detail"]


def test_the_caller_cannot_choose_the_decision_date(client, files):
    resp = _post(client, files, ALPHA_KEY, data={"as_of": "2020-01-01"})
    assert resp.status_code == 200
    assert resp.headers["x-alibi-as-of"] == datetime.now(UTC).date().isoformat()


def test_bad_engine_config_is_refused_before_anything_is_written(
    client, files, app_engine, monkeypatch
):
    data = yaml.safe_load((REPO_ROOT / "config" / "engine.yaml").read_text())
    data["charge_types"]["refund_issued_item_not_returned"]["pods"]["returns"]["max_days_after"] = (
        60
    )
    monkeypatch.setattr("app.api.agent.load_engine_config", lambda: parse_engine_config(data))
    before = {org: _rows(app_engine, org, t.charges) for org in (ALPHA, BRAVO)}
    audit_before = _rows(app_engine, ALPHA, t.audit_events)
    resp = _post(client, files, ALPHA_KEY)
    assert resp.status_code == 500
    assert "engine configuration refused" in resp.json()["detail"]
    assert {org: _rows(app_engine, org, t.charges) for org in (ALPHA, BRAVO)} == before
    assert _rows(app_engine, ALPHA, t.audit_events) == audit_before


# --- key configuration ----------------------------------------------------------------


def test_keys_are_read_from_settings_as_hashes(monkeypatch):
    monkeypatch.setenv("ALIBI_API_KEYS", f" {ALPHA}:{hash_key(ALPHA_KEY)} ,, ")
    get_settings.cache_clear()
    try:
        assert configured_keys() == {hash_key(ALPHA_KEY): ALPHA}
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "value",
    [
        "org_x",
        "org_x:nothex",
        f":{'a' * 64}",
        f"org x:{'a' * 64}",
        f"org_x:{'a' * 64},org_y:{'a' * 64}",
    ],
)
def test_malformed_or_ambiguous_key_config_is_refused(value):
    with pytest.raises(ValueError, match="ALIBI_API_KEYS"):
        parse_api_keys(value)


def test_org_for_key_matches_only_the_exact_key():
    keys = parse_api_keys(f"{ALPHA}:{hash_key(ALPHA_KEY)},{BRAVO}:{hash_key(BRAVO_KEY)}")
    assert org_for_key(ALPHA_KEY, keys) == ALPHA
    assert org_for_key(BRAVO_KEY, keys) == BRAVO
    assert org_for_key(ALPHA_KEY.upper(), keys) is None
    assert org_for_key(None, keys) is None and org_for_key("", keys) is None


def test_cli_api_key_prints_a_key_and_its_hash_entry():
    from typer.testing import CliRunner

    from app import cli

    out = CliRunner().invoke(cli.app, ["api-key", "--org", ALPHA]).output
    key = out.splitlines()[0].split(": ", 1)[1].strip()
    entry = out.splitlines()[1].split(": ", 1)[1].strip()
    assert entry == f"{ALPHA}:{hash_key(key)}"
    assert parse_api_keys(entry) == {hash_key(key): ALPHA}
    assert len(key) >= 40


def test_another_orgs_malformed_row_is_not_stored_under_the_callers_org(client, files, app_engine):
    report = (files / "report.csv").read_text()
    tail = "SKU,FN,FBA,,inbound_defect_fee,notanumber,1.00,2026-07-01\n"  # bad quantity
    bad = f"FEE-BAD-1,fee_report,UNIT-X,{BRAVO},{tail}"
    own_bad = f"FEE-BAD-2,fee_report,UNIT-Y,{ALPHA},{tail}"
    (files / "report_bad.csv").write_text(report + bad + own_bad)
    upload = [("report", ("report.csv", (files / "report_bad.csv").read_bytes(), "text/csv"))]
    for pod in PODS:
        body = (files / "upstream" / f"{pod}_api.csv").read_bytes()
        upload.append(("upstream", (f"{pod}_api.csv", body, "text/csv")))
    resp = client.post("/agent", files=upload, headers={"X-API-Key": ALPHA_KEY})
    assert resp.status_code == 200
    assert resp.headers["x-alibi-rows-quarantined"] == "1"  # alpha's own bad row only
    with org_session(app_engine, ALPHA) as s:
        raws: list[dict[str, str]] = list(s.execute(sa.select(t.quarantined_rows.c.raw)).scalars())
    assert any(r.get("line_id") == "FEE-BAD-2" for r in raws)
    assert not any(r.get("org_id") == BRAVO for r in raws)
    assert _rows(app_engine, BRAVO, t.quarantined_rows) == 0
