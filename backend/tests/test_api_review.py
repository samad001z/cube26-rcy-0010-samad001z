"""Review endpoints: auth from the key only, cross-org reads answer 404, the evidence trail
comes back with hash checks, overrides go through the API, and a failed database answers
503 instead of a partial answer."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from app.api.agent import db_engine
from app.api.auth import configured_keys, hash_key, parse_api_keys
from app.db import repo
from app.db.session import org_session
from app.main import app
from app.models.decision import DecisionRecord
from tests.conftest import ALPHA, BRAVO

ALPHA_KEY, BRAVO_KEY = "alpha-review-key-000000000", "bravo-review-key-111111111"


def _keys() -> dict[str, str]:
    return parse_api_keys(f"{ALPHA}:{hash_key(ALPHA_KEY)},{BRAVO}:{hash_key(BRAVO_KEY)}")


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
    post = client.post(
        f"/decisions/{alpha_id}/overrides",
        json={"new_decision": "DO_NOT_CLAIM", "reason": "not mine to judge", "reviewer": "x"},
        headers=_h(BRAVO_KEY),
    )
    assert post.status_code == 404


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
    d = next(
        x for x in _latest(app_engine, BRAVO) if x.decision.value == "REVIEW" and x.claim is None
    )
    detail = client.get(f"/decisions/{d.record_id}", headers=_h(BRAVO_KEY)).json()
    before = detail["record"]["decision"]
    target = "DO_NOT_CLAIM" if before != "DO_NOT_CLAIM" else "REVIEW"
    r = client.post(
        f"/decisions/{d.record_id}/overrides",
        json={"new_decision": target, "reason": "weights checked on the shelf", "reviewer": "ravi"},
        headers=_h(BRAVO_KEY),
    )
    assert r.status_code == 201, r.text
    assert r.json()["record"]["decision"] == target
    assert r.json()["record"]["outcome"]["decided_by"] == "human:ravi"
    after = client.get(f"/decisions/{d.record_id}", headers=_h(BRAVO_KEY)).json()
    assert after["record"]["status"] == "overridden"
    assert after["engine_record"]["decision"] == d.decision.value  # engine row untouched
    assert after["overrides"][-1]["override"]["reason"] == "weights checked on the shelf"
    listed = client.get("/decisions", headers=_h(BRAVO_KEY)).json()["items"]
    row = next(i for i in listed if i["record_id"] == d.record_id)
    assert row["decision"] == target and row["engine_decision"] == d.decision.value
    assert row["override_count"] == len(after["overrides"])
    # The same change again is a no-op and is refused.
    again = client.post(
        f"/decisions/{d.record_id}/overrides",
        json={"new_decision": target, "reason": "weights checked on the shelf", "reviewer": "ravi"},
        headers=_h(BRAVO_KEY),
    )
    assert again.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"new_decision": "CLAIM", "reason": "", "reviewer": "asha"},
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
    r = client.post(f"/decisions/{d.record_id}/overrides", json=payload, headers=_h(ALPHA_KEY))
    assert r.status_code == 422


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
