"""Review endpoints: auth from the key only, cross-org reads answer 404, the evidence trail
comes back with hash checks, overrides go through the API, and a failed database answers
503 instead of a partial answer."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from app.api.agent import db_engine
from app.api.auth import configured_keys, hash_key, parse_api_keys
from app.db import repo
from app.db.session import org_session
from app.main import app
from app.models.decision import DecisionRecord
from app.pipeline import run_org
from tests.conftest import ALPHA, AS_OF, BRAVO
from tests.test_overrides import _setup

ALPHA_KEY, BRAVO_KEY = "alpha-review-key-000000000", "bravo-review-key-111111111"
# One synthetic org per tampering test, so no test sees another's edits.
_RUN = uuid.uuid4().hex[:8]
SYN_ORGS = {f"org_test_api_rev_{_RUN}_{n}": f"synthetic-review-key-{n}-{_RUN}" for n in range(4)}


def _keys() -> dict[str, str]:
    pairs = [(ALPHA, ALPHA_KEY), (BRAVO, BRAVO_KEY), *SYN_ORGS.items()]
    return parse_api_keys(",".join(f"{org}:{hash_key(key)}" for org, key in pairs))


def _syn(n: int) -> tuple[str, str]:
    return list(SYN_ORGS.items())[n]


@pytest.fixture
def client(app_engine: Engine, loaded) -> Iterator[TestClient]:
    app.dependency_overrides[db_engine] = lambda: app_engine
    app.dependency_overrides[configured_keys] = _keys
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _h(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


def _latest(engine: Engine, org: str) -> list[DecisionRecord]:
    with org_session(engine, org) as s:
        run = repo.list_runs(s)[0]
        return repo.list_decisions(s, run.run_id)


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/runs"),
        ("get", "/decisions"),
        ("get", "/decisions/DEC-x"),
        ("post", "/decisions/DEC-x/overrides"),
    ],
)
def test_every_review_endpoint_needs_a_key(client, method, path):
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers=_h("wrong")).status_code == 401


def test_runs_and_decisions_list_the_newest_run_of_the_callers_org(client, app_engine):
    runs = client.get("/runs", headers=_h(ALPHA_KEY)).json()
    assert runs and all(sum(r["counts"].values()) == r["charges"] for r in runs)
    body = client.get("/decisions", headers=_h(ALPHA_KEY)).json()
    assert body["run"]["run_id"] == runs[0]["run_id"]
    latest = _latest(app_engine, ALPHA)
    assert [i["record_id"] for i in body["items"]] == [d.record_id for d in latest]
    assert {i["line_id"] for i in body["items"]} == {d.subject.line_id for d in latest}
    item = body["items"][0]
    for field in ("decision", "engine_decision", "status", "reason_code", "confidence", "reason"):
        assert field in item


def test_decisions_of_a_named_run_and_unknown_run(client):
    runs = client.get("/runs", headers=_h(ALPHA_KEY)).json()
    oldest = runs[-1]["run_id"]
    body = client.get("/decisions", params={"run_id": oldest}, headers=_h(ALPHA_KEY)).json()
    assert body["run"]["run_id"] == oldest
    missing = client.get(
        "/decisions",
        params={"run_id": "00000000-0000-0000-0000-000000000000"},
        headers=_h(ALPHA_KEY),
    )
    assert missing.status_code == 404


def test_bravo_never_sees_alphas_runs_or_decisions(client, app_engine):
    alpha_runs = {r["run_id"] for r in client.get("/runs", headers=_h(ALPHA_KEY)).json()}
    bravo_runs = {r["run_id"] for r in client.get("/runs", headers=_h(BRAVO_KEY)).json()}
    assert alpha_runs and bravo_runs and not (alpha_runs & bravo_runs)
    alpha_id = _latest(app_engine, ALPHA)[0].record_id
    assert client.get(f"/decisions/{alpha_id}", headers=_h(BRAVO_KEY)).status_code == 404
    got = client.get("/decisions", params={"run_id": next(iter(alpha_runs))}, headers=_h(BRAVO_KEY))
    assert got.status_code == 404
    with org_session(app_engine, ALPHA) as s:
        before = len(repo.list_overrides(s, alpha_id))
    post = client.post(
        f"/decisions/{alpha_id}/overrides",
        json={"new_decision": "DO_NOT_CLAIM", "reason": "not mine to judge", "reviewer": "x"},
        headers=_h(BRAVO_KEY),
    )
    assert post.status_code == 404
    with org_session(app_engine, ALPHA) as s:
        assert len(repo.list_overrides(s, alpha_id)) == before


def test_detail_returns_the_evidence_trail_with_hash_checks(client, app_engine):
    d = next(x for x in _latest(app_engine, ALPHA) if x.evidence_considered)
    body = client.get(f"/decisions/{d.record_id}", headers=_h(ALPHA_KEY)).json()
    assert body["engine_record"]["content_hash"] == d.content_hash
    assert body["charge"]["line_id"] == d.subject.line_id
    assert body["integrity_problems"] == []
    assert len(body["evidence"]) == len(d.evidence_considered)
    for e in body["evidence"]:
        assert e["record"] is not None
        assert e["hash_matches_decision"] and e["record_hash_verifies"]
    cited = {(c.agent, c.id) for c in d.citations if c.kind == "evidence"}
    assert {(e["agent"], e["record_id"]) for e in body["evidence"] if e["cited"]} == cited
    assert any(h["record_id"] == d.record_id for h in body["line_history"])


def test_override_through_the_api_then_detail_shows_it(client, app_engine):
    # A record nobody has overridden yet (the `loaded` fixture overrides one per org), moved
    # to a decision different from the engine's, so engine and effective values must differ.
    with org_session(app_engine, BRAVO) as s:
        latest = _latest(app_engine, BRAVO)
        done = repo.overrides_by_record(s, [x.record_id for x in latest])
    d = next(x for x in latest if x.decision.value == "REVIEW" and x.record_id not in done)
    r = client.post(
        f"/decisions/{d.record_id}/overrides",
        json={"new_decision": "DO_NOT_CLAIM", "reason": "weights checked", "reviewer": "ravi"},
        headers=_h(BRAVO_KEY),
    )
    assert r.status_code == 201, r.text
    assert r.json()["record"]["decision"] == "DO_NOT_CLAIM"
    assert r.json()["record"]["outcome"]["decided_by"] == "human:ravi"
    after = client.get(f"/decisions/{d.record_id}", headers=_h(BRAVO_KEY)).json()
    assert after["record"]["status"] == "overridden"
    assert after["record"]["decision"] == "DO_NOT_CLAIM"
    assert after["engine_record"]["decision"] == "REVIEW"  # engine row untouched
    assert after["engine_record"]["content_hash"] == d.content_hash
    assert [o["override"]["reason"] for o in after["overrides"]] == ["weights checked"]
    assert after["integrity_problems"] == []
    listed = client.get("/decisions", headers=_h(BRAVO_KEY)).json()["items"]
    row = next(i for i in listed if i["record_id"] == d.record_id)
    assert (row["decision"], row["engine_decision"]) == ("DO_NOT_CLAIM", "REVIEW")
    assert row["override_count"] == 1 and row["status"] == "overridden"
    # The same change again is a no-op and is refused.
    again = client.post(
        f"/decisions/{d.record_id}/overrides",
        json={"new_decision": "DO_NOT_CLAIM", "reason": "weights checked", "reviewer": "ravi"},
        headers=_h(BRAVO_KEY),
    )
    assert again.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"new_decision": "CLAIM", "reason": "", "reviewer": "asha"},
        {"new_decision": "CLAIM", "reason": " \t\n ", "reviewer": "asha"},
        {"new_decision": "CLAIM", "reviewer": "asha"},
        {"new_decision": "CLAIM", "reason": "good reason"},
        {"new_decision": "MAYBE", "reason": "good reason", "reviewer": "asha"},
        {"new_decision": "CLAIM", "reason": "good reason", "reviewer": "asha", "amount": "99"},
        {
            "new_decision": "CLAIM",
            "reason": "good reason",
            "reviewer": "asha",
            "organization_id": BRAVO,
        },
    ],
)
def test_bad_override_bodies_are_refused(client, app_engine, payload):
    d = _latest(app_engine, ALPHA)[0]
    with org_session(app_engine, ALPHA) as s:
        before = len(repo.list_overrides(s, d.record_id))
    r = client.post(f"/decisions/{d.record_id}/overrides", json=payload, headers=_h(ALPHA_KEY))
    assert r.status_code == 422
    with org_session(app_engine, ALPHA) as s:
        assert len(repo.list_overrides(s, d.record_id)) == before


def test_unknown_decision_is_404(client):
    assert client.get("/decisions/DEC-nope", headers=_h(ALPHA_KEY)).status_code == 404


# --- fail open at the API: a dead database is a 503, never a partial or empty answer -----


@pytest.fixture
def dead_db_client(loaded) -> Iterator[TestClient]:
    dead = create_engine(
        "postgresql+psycopg://alibi_app:x@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    app.dependency_overrides[db_engine] = lambda: dead
    app.dependency_overrides[configured_keys] = _keys
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        dead.dispose()


@pytest.mark.parametrize(
    "method, path, kwargs",
    [
        ("get", "/runs", {}),
        ("get", "/decisions", {}),
        ("get", "/decisions/DEC-x", {}),
        (
            "post",
            "/decisions/DEC-x/overrides",
            {"json": {"new_decision": "CLAIM", "reason": "good reason", "reviewer": "asha"}},
        ),
    ],
)
def test_review_endpoints_answer_503_when_the_database_is_down(
    dead_db_client, method, path, kwargs
):
    r = getattr(dead_db_client, method)(path, headers=_h(ALPHA_KEY), **kwargs)
    assert r.status_code == 503
    assert "dependency unavailable" in r.json()["detail"]


# --- integrity and history signals reach the API (test-guardian and rules-guardian reviews)


def _owner_exec(owner_engine: Engine, org: str, sql: str, **params: object) -> int:
    with owner_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": org})
        return conn.execute(text(sql), params).rowcount


def test_tampered_override_shows_in_list_and_detail_and_blocks_overrides(
    client, app_engine, owner_engine
):
    org, key = _syn(0)
    d = _setup(app_engine, org)["SYN-2"]
    ok = client.post(
        f"/decisions/{d.record_id}/overrides",
        json={"new_decision": "DO_NOT_CLAIM", "reason": "checked on the shelf", "reviewer": "a"},
        headers=_h(key),
    )
    assert ok.status_code == 201
    changed = _owner_exec(
        owner_engine,
        org,
        "UPDATE decision_overrides SET body = jsonb_set(body, '{override,new_decision}', "
        "'\"CLAIM\"') WHERE decision_record_id = :r",
        r=d.record_id,
    )
    assert changed == 1
    detail = client.get(f"/decisions/{d.record_id}", headers=_h(key)).json()
    assert any("content hash does not verify" in p for p in detail["integrity_problems"])
    assert any("columns do not match" in p for p in detail["integrity_problems"])
    listed = client.get("/decisions", headers=_h(key)).json()["items"]
    row = next(i for i in listed if i["record_id"] == d.record_id)
    assert row["integrity_problems"]
    refused = client.post(
        f"/decisions/{d.record_id}/overrides",
        json={"new_decision": "REVIEW", "reason": "back to review", "reviewer": "a"},
        headers=_h(key),
    )
    assert refused.status_code == 409


def test_changed_evidence_shows_as_hash_mismatch(client, app_engine, owner_engine):
    org, key = _syn(1)
    d = _setup(app_engine, org)["SYN-1"]
    cited = next(c for c in d.citations if c.kind == "evidence")
    _owner_exec(
        owner_engine,
        org,
        "UPDATE evidence_records SET content_hash = 'x' || content_hash "
        "WHERE record_id = :r AND agent = :a",
        r=cited.id,
        a=cited.agent,
    )
    detail = client.get(f"/decisions/{d.record_id}", headers=_h(key)).json()
    ev = next(e for e in detail["evidence"] if e["record_id"] == cited.id)
    assert ev["cited"] and ev["hash_matches_decision"] is False


def test_rerun_keeps_an_earlier_override_visible_and_the_old_record_read_only(client, app_engine):
    org, key = _syn(2)
    first = _setup(app_engine, org)["SYN-2"]
    r = client.post(
        f"/decisions/{first.record_id}/overrides",
        json={
            "new_decision": "DO_NOT_CLAIM",
            "reason": "label looks fine",
            "reviewer": "a",
        },
        headers=_h(key),
    )
    assert r.status_code == 201
    second = {d.subject.line_id: d for d in run_org(app_engine, org, AS_OF).decisions}["SYN-2"]
    listed = client.get("/decisions", headers=_h(key)).json()
    assert listed["run"]["run_id"] == second.run_id
    row = next(i for i in listed["items"] if i["record_id"] == second.record_id)
    assert row["decision"] == "REVIEW" and row["override_count"] == 0
    assert row["earlier_override"] == {
        "record_id": first.record_id,
        "decision": "DO_NOT_CLAIM",
        "reviewer": "a",
        "at": row["earlier_override"]["at"],
        "reason": "label looks fine",
    }
    old = client.get(f"/decisions/{first.record_id}", headers=_h(key)).json()
    new = client.get(f"/decisions/{second.record_id}", headers=_h(key)).json()
    assert (old["overridable"], new["overridable"]) == (False, True)
    stale = client.post(
        f"/decisions/{first.record_id}/overrides",
        json={"new_decision": "CLAIM", "reason": "claim it after all", "reviewer": "a"},
        headers=_h(key),
    )
    assert stale.status_code == 409 and "newer run" in stale.json()["detail"]


def test_detail_says_why_claim_is_not_offered(client, app_engine):
    with org_session(app_engine, ALPHA) as s:
        loss = repo.list_decisions_for_line(s, "FEE-0071-2")[-1]
    body = client.get(f"/decisions/{loss.record_id}", headers=_h(ALPHA_KEY)).json()
    assert "loss event is never CLAIM" in body["claim_refusal"]
    r = client.post(
        f"/decisions/{loss.record_id}/overrides",
        json={"new_decision": "CLAIM", "reason": "try to claim it", "reviewer": "a"},
        headers=_h(ALPHA_KEY),
    )
    assert r.status_code == 409


def test_detail_gives_captured_at_custody_window_and_deadline_as_fields(client, app_engine):
    decisions = _latest(app_engine, ALPHA)
    d = next(x for x in decisions if x.evidence_considered)
    body = client.get(f"/decisions/{d.record_id}", headers=_h(ALPHA_KEY)).json()
    for e in body["evidence"]:
        assert e["captured_at"] == e["record"]["captured_at"]
        w = e["custody_window"]
        assert w is not None and w["start"] < w["end"] and w["anchor"] == "posted_date"
        assert w["posted_date"] == body["charge"]["posted_date"]
        # The same judgement the engine wrote into the trace at decision time.
        assert w["captured_inside"] == (" inside custody window " in e["why"])
        assert f"[{w['start'][:10]}, {w['end'][:10]})" in e["why"]
    statuses = {}
    for x in decisions:
        got = client.get(f"/decisions/{x.record_id}", headers=_h(ALPHA_KEY)).json()["deadline"]
        verdict = x.check("within_filing_window").verdict.value
        assert got["verdict"] == verdict
        assert got["detail"] == x.check("within_filing_window").detail
        statuses[x.subject.line_id] = got["status"]
    assert statuses["FEE-0071-2"] == "passed"
    assert {"passed", "not_verified"} <= set(statuses.values())
    assert set(statuses.values()) <= {"open", "passed", "not_yet_open", "not_verified"}


def test_decisions_filter_by_effective_decision_charge_type_and_rule(client, app_engine):
    h = _h(ALPHA_KEY)
    full = client.get("/decisions", headers=h).json()
    items = full["items"]
    assert sum(full["counts"].values()) == len(items) == full["run"]["charges"]
    assert set(full["facets"]["charge_type"]) == {i["charge_type"] for i in items}
    for dec in ("CLAIM", "DO_NOT_CLAIM", "REVIEW"):
        got = client.get("/decisions", params={"decision": dec}, headers=h).json()
        assert [i["record_id"] for i in got["items"]] == [
            i["record_id"] for i in items if i["decision"] == dec
        ]
        assert got["counts"] == full["counts"]  # totals describe the whole run
    ct = next(i["charge_type"] for i in items)
    rule = next(i["rule_id"] for i in items if i["charge_type"] == ct)
    got = client.get("/decisions", params={"charge_type": ct, "rule_id": rule}, headers=h).json()
    expected = [i for i in items if i["charge_type"] == ct and i["rule_id"] == rule]
    assert got["items"] == expected and expected
    assert got["filters"] == {"decision": None, "charge_type": ct, "rule_id": rule}
    # The decision filter reads the effective decision: an overridden line moves with it.
    overridden = next((i for i in items if i["override_count"] > 0), None)
    assert overridden is not None  # the `loaded` fixture overrides one decision per org
    assert overridden["decision"] != overridden["engine_decision"]
    by_effective = client.get(
        "/decisions", params={"decision": overridden["decision"]}, headers=h
    ).json()["items"]
    by_engine = client.get(
        "/decisions", params={"decision": overridden["engine_decision"]}, headers=h
    ).json()["items"]
    assert overridden["record_id"] in {i["record_id"] for i in by_effective}
    assert overridden["record_id"] not in {i["record_id"] for i in by_engine}
    assert client.get("/decisions", params={"decision": "MAYBE"}, headers=h).status_code == 422
    assert client.get("/decisions", params={"charge_type": "x"}, headers=h).status_code == 422
