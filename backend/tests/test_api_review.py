"""Review endpoints: auth from the key only, cross-org reads answer 404, the evidence trail
comes back with hash checks, overrides go through the API, and a failed database answers
503 instead of a partial answer."""

import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from app.api.agent import db_engine
from app.api.auth import configured_keys, hash_key, parse_api_keys
from app.db import repo
from app.db.session import org_session
from app.main import app
from app.models.charge import Charge, SourceRef
from app.models.contract import EvidenceRecord
from app.models.decision import DecisionRecord
from app.models.vocab import ChargeType, ReportType
from app.pipeline import run_org
from tests.conftest import ALPHA, AS_OF, BRAVO
from tests.factories import charge, prep_all_pass
from tests.test_overrides import _setup

ALPHA_KEY, BRAVO_KEY = "alpha-review-key-000000000", "bravo-review-key-111111111"
# One synthetic org per tampering test, so no test sees another's edits.
_RUN = uuid.uuid4().hex[:8]
SYN_ORGS = {f"org_test_api_rev_{_RUN}_{n}": f"synthetic-review-key-{n}-{_RUN}" for n in range(10)}


def _keys() -> dict[str, str]:
    pairs = [(ALPHA, ALPHA_KEY), (BRAVO, BRAVO_KEY), *SYN_ORGS.items()]
    return parse_api_keys(",".join(f"{org}:{hash_key(key)}" for org, key in pairs))


def _today_window() -> set[str]:
    """Today, or yesterday if the request ran just before midnight UTC."""
    now = datetime.now(UTC).date()
    return {now.isoformat(), (now - timedelta(days=1)).isoformat()}


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
        ("get", "/me"),
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
        # What the run's own check said is kept next to today's judgement.
        assert got["at_decision"] == {
            "verdict": x.check("within_filing_window").verdict.value,
            "detail": x.check("within_filing_window").detail,
        }
        assert got["as_of"] in _today_window()
        statuses[x.subject.line_id] = got
    passed = statuses["FEE-0071-2"]  # damaged in warehouse, 60-day window long closed
    assert passed["status"] == "passed" and passed["deadline"] is not None
    assert passed["deadline"] < passed["as_of"]
    weight = next(g for line, g in statuses.items() if line == "FEE-0002-1")
    assert weight["status"] == "not_verified" and weight["deadline"] is None
    assert {g["status"] for g in statuses.values()} <= {
        "open",
        "passed",
        "not_yet_open",
        "not_verified",
    }


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


# --- test-guardian second review: filters one at a time, earlier-override selection, ---
# --- deadline states judged today, custody window edges and guards                   ---


def _load(engine: Engine, org: str, charges: list[Charge], records: list[EvidenceRecord]):
    with org_session(engine, org) as s:
        fid = repo.upsert_ingest_file(s, org, "syn.csv", uuid.uuid4().hex * 2, "fee_report")
        repo.insert_charges(s, charges, fid)
        if records:
            refs = {
                (r.agent, r.record_id): SourceRef(file_sha256="c" * 64, row=i, raw={})
                for i, r in enumerate(records)
            }
            repo.insert_records(s, records, refs, fid)
    return {d.subject.line_id: d for d in run_org(engine, org, AS_OF).decisions}


def test_each_filter_works_on_its_own_and_counts_are_effective(client):
    h = _h(ALPHA_KEY)
    full = client.get("/decisions", headers=h).json()
    items = full["items"]
    types = {i["charge_type"] for i in items}
    rules = {i["rule_id"] for i in items}
    assert len(types) > 1 and len(rules) > 1  # otherwise a dropped filter would go unseen
    for ct in types:
        got = client.get("/decisions", params={"charge_type": ct}, headers=h).json()["items"]
        assert [i["record_id"] for i in got] == [
            i["record_id"] for i in items if i["charge_type"] == ct
        ]
    for rule in rules:
        got = client.get("/decisions", params={"rule_id": rule}, headers=h).json()["items"]
        assert [i["record_id"] for i in got] == [
            i["record_id"] for i in items if i["rule_id"] == rule
        ]
    effective = Counter(i["decision"] for i in items)
    engine = Counter(i["engine_decision"] for i in items)
    assert effective != engine  # the `loaded` fixture overrode one alpha decision
    assert full["counts"] == {d: effective.get(d, 0) for d in ("CLAIM", "DO_NOT_CLAIM", "REVIEW")}


def _override_api(client, key: str, record_id: str, new: str, reason: str, who: str = "a"):
    r = client.post(
        f"/decisions/{record_id}/overrides",
        json={"new_decision": new, "reason": reason, "reviewer": who},
        headers=_h(key),
    )
    assert r.status_code == 201, r.text


def test_earlier_override_is_the_newest_one_from_an_earlier_run_only(client, app_engine):
    org, key = _syn(3)
    run1 = _setup(app_engine, org)["SYN-2"]
    _override_api(client, key, run1.record_id, "DO_NOT_CLAIM", "run one says close")
    run2 = {d.subject.line_id: d for d in run_org(app_engine, org, AS_OF).decisions}["SYN-2"]
    _override_api(client, key, run2.record_id, "DO_NOT_CLAIM", "run two first", "b")
    _override_api(client, key, run2.record_id, "REVIEW", "run two second", "c")
    run3 = {d.subject.line_id: d for d in run_org(app_engine, org, AS_OF).decisions}["SYN-2"]

    def row(run_id: str) -> dict[str, Any]:
        items = client.get("/decisions", params={"run_id": run_id}, headers=_h(key)).json()
        return next(i for i in items["items"] if i["line_id"] == "SYN-2")

    newest = row(run3.run_id)["earlier_override"]
    assert newest is not None
    assert (newest["record_id"], newest["decision"], newest["reviewer"]) == (
        run2.record_id,
        "REVIEW",
        "c",
    )
    assert row(run2.run_id)["earlier_override"] is None  # its own override is not "earlier"
    assert row(run1.run_id)["earlier_override"] is None  # run two's is later, not earlier


def test_deadline_states_are_judged_today(client, app_engine):
    org, key = _syn(4)
    today = datetime.now(UTC).date()
    refund = ChargeType.REFUND_ISSUED_ITEM_NOT_RETURNED
    decided = _load(
        app_engine,
        org,
        [
            charge(
                "REF-OPEN",
                org=org,
                charge_type=refund,
                posted=today - timedelta(days=90),
                order_id="O-1",
                unit_id="U-A",
                amount="0.00",
            ),
            charge(
                "REF-SOON",
                org=org,
                charge_type=refund,
                posted=today - timedelta(days=10),
                order_id="O-2",
                unit_id="U-B",
                amount="0.00",
            ),
            charge(
                "REF-GONE",
                org=org,
                charge_type=refund,
                posted=today - timedelta(days=200),
                order_id="O-3",
                unit_id="U-C",
                amount="0.00",
            ),
        ],
        [],
    )
    got = {
        line: client.get(f"/decisions/{d.record_id}", headers=_h(key)).json()["deadline"]
        for line, d in decided.items()
    }
    assert got["REF-OPEN"]["status"] == "open"
    assert got["REF-OPEN"]["deadline"] == (today + timedelta(days=30)).isoformat()
    assert got["REF-SOON"]["status"] == "not_yet_open"
    assert got["REF-SOON"]["opens"] == (today + timedelta(days=50)).isoformat()
    assert got["REF-GONE"]["status"] == "passed"
    # A decision recorded 60 days ago: then the window was not yet open, today it is. The
    # page shows today's state, with the decision's own check kept beside it.
    old = decided["REF-OPEN"]
    aged = old.model_copy(
        update={
            "record_id": f"{old.record_id}-aged",
            "run_id": str(uuid.uuid4()),
            "captured_at": old.captured_at - timedelta(days=60),
        }
    ).with_hash()
    with org_session(app_engine, org) as s:
        repo.insert_decision(s, aged)
    aged_got = client.get(f"/decisions/{aged.record_id}", headers=_h(key)).json()["deadline"]
    assert aged_got["status"] == "open" and aged_got["as_of"] in _today_window()


def test_custody_window_end_is_exclusive_and_outside_records_say_so(client, app_engine):
    org, key = _syn(5)
    posted_midnight = datetime(2026, 7, 18, tzinfo=UTC)  # the factory charge's posted date
    decided = _load(
        app_engine,
        org,
        [charge("SYN-W", org=org, defect_category="label")],
        [
            prep_all_pass("PRP-IN", org=org, captured=posted_midnight - timedelta(seconds=1)),
            prep_all_pass("PRP-EDGE", org=org, captured=posted_midnight),
        ],
    )
    body = client.get(f"/decisions/{decided['SYN-W'].record_id}", headers=_h(key)).json()
    ev = {e["record_id"]: e for e in body["evidence"]}
    assert ev["PRP-IN"]["custody_window"]["captured_inside"] is True
    assert ev["PRP-EDGE"]["custody_window"]["captured_inside"] is False
    assert ev["PRP-EDGE"]["custody_window"]["end"] == "2026-07-18T00:00:00Z"
    assert ev["PRP-IN"]["usable"] and not ev["PRP-EDGE"]["usable"]


def test_custody_window_is_withheld_when_the_engine_config_changed(client, app_engine, monkeypatch):
    org, key = _syn(6)
    decided = _load(
        app_engine,
        org,
        [charge("SYN-C", org=org, defect_category="label")],
        [prep_all_pass("PRP-C", org=org)],
    )
    from app.core.rules import load_engine_config

    changed = load_engine_config().model_copy(update={"config_hash": "f" * 64})
    monkeypatch.setattr("app.api.review.load_engine_config", lambda: changed)
    body = client.get(f"/decisions/{decided['SYN-C'].record_id}", headers=_h(key)).json()
    assert [e["custody_window"] for e in body["evidence"]] == [None]
    assert "inside custody window" in body["evidence"][0]["why"]  # the stored text remains


def test_charge_changed_since_the_decision_withholds_window_and_deadline(client, app_engine):
    """If the stored charge no longer hashes to what the decision recorded, the page does
    not compute a custody window or a deadline from it (the stored text remains)."""
    org, key = _syn(7)
    decided = _load(
        app_engine,
        org,
        [charge("SYN-H", org=org, defect_category="label")],
        [prep_all_pass("PRP-H", org=org)],
    )
    d = decided["SYN-H"]
    v = d.model_copy(
        update={
            "record_id": f"{d.record_id}-h",
            "run_id": str(uuid.uuid4()),
            "subject": d.subject.model_copy(update={"charge_content_hash": "0" * 64}),
        }
    ).with_hash()
    with org_session(app_engine, org) as s:
        repo.insert_decision(s, v)
    body = client.get(f"/decisions/{v.record_id}", headers=_h(key)).json()
    assert body["deadline"]["status"] == "unknown"
    assert body["deadline"]["at_decision"]["detail"] == d.check("within_filing_window").detail
    assert [e["custody_window"] for e in body["evidence"]] == [None]


# --- GET /me and totals (docs/BACKLOG.md, Phase 2) ---------------------------------------


def test_me_names_the_callers_organisation_only(client):
    assert client.get("/me", headers=_h(ALPHA_KEY)).json() == {"organization_id": ALPHA}
    assert client.get("/me", headers=_h(BRAVO_KEY)).json() == {"organization_id": BRAVO}
    assert client.get("/me", headers=_h("not-a-key")).status_code == 401


def test_totals_are_decimal_sums_per_effective_decision(client, app_engine):
    """Fee lines count as charged; a refund line and a loss event do not (their amount is
    money paid to the seller). Claimable sums the effective claims. Overrides move them."""
    org, key = _syn(8)
    fees = [
        charge("SYN-1", defect_category="label", org=org),  # CLAIM 2.00
        charge("SYN-2", unit_id="U-2", amount="3.15", org=org),  # REVIEW, no evidence
        charge("SYN-3", unit_id="U-3", amount="1.10", org=org),  # refunded in full
        charge(
            "SYN-4",
            unit_id="U-3",
            amount="1.10",
            report_type=ReportType.REIMBURSEMENT_REPORT,
            org=org,
        ),
        charge(
            "SYN-5",
            unit_id="U-5",
            amount="4.00",
            charge_type=ChargeType.LOST_INBOUND,
            report_type=ReportType.INVENTORY_ADJUSTMENT,
            org=org,
        ),
    ]
    r = prep_all_pass("SYN-PRP-1", org=org)
    with org_session(app_engine, org) as s:
        fid = repo.upsert_ingest_file(s, org, "totals.csv", uuid.uuid4().hex * 2, "fee_report")
        repo.insert_charges(s, fees, fid)
        repo.insert_records(
            s, [r], {(r.agent, r.record_id): SourceRef(file_sha256="b" * 64, row=1, raw={})}, fid
        )
    run = run_org(app_engine, org, AS_OF)
    decided = {d.subject.line_id: d.decision.value for d in run.decisions}
    assert decided == {
        "SYN-1": "CLAIM",
        "SYN-2": "REVIEW",
        "SYN-3": "DO_NOT_CLAIM",
        "SYN-4": "DO_NOT_CLAIM",
        "SYN-5": "REVIEW",
    }

    totals = client.get("/decisions", headers=_h(key)).json()["totals"]
    assert totals == {
        "ALL": {"count": 5, "fees_charged": {"USD": "6.25"}, "claimable": {"USD": "2.00"}},
        "CLAIM": {"count": 1, "fees_charged": {"USD": "2.00"}, "claimable": {"USD": "2.00"}},
        "DO_NOT_CLAIM": {"count": 2, "fees_charged": {"USD": "1.10"}, "claimable": {}},
        "REVIEW": {"count": 2, "fees_charged": {"USD": "3.15"}, "claimable": {}},
    }
    # Filters narrow items, never the totals.
    filtered = client.get("/decisions?decision=CLAIM", headers=_h(key)).json()
    assert len(filtered["items"]) == 1 and filtered["totals"] == totals

    items = client.get("/decisions", headers=_h(key)).json()["items"]
    syn2 = next(i for i in items if i["line_id"] == "SYN-2")
    res = client.post(
        f"/decisions/{syn2['record_id']}/overrides",
        headers=_h(key),
        json={"new_decision": "DO_NOT_CLAIM", "reason": "fee is correct", "reviewer": "asha"},
    )
    assert res.status_code == 201, res.text
    moved = client.get("/decisions", headers=_h(key)).json()["totals"]
    assert moved["REVIEW"] == {"count": 1, "fees_charged": {}, "claimable": {}}
    assert moved["DO_NOT_CLAIM"] == {"count": 3, "fees_charged": {"USD": "4.25"}, "claimable": {}}
    assert moved["ALL"] == totals["ALL"]
