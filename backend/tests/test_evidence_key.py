"""Evidence is keyed by (organization_id, agent, record_id): record_id is unique only within
a pod, so a prep record and a returns record may share an id (D-018, review triage)."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.adapters.csv_v0 import attachment_key
from app.claims.validator import StoredRecord, validate
from app.db import repo
from app.db.session import org_session
from app.models.charge import Charge, SourceRef
from app.models.contract import EvidenceRecord
from app.models.decision import Citation
from app.models.vocab import ChargeType, Decision, RecordStatus, ReportType
from app.pipeline import run_org
from tests.conftest import AS_OF
from tests.factories import charge, check, prep_all_pass, record
from tests.test_claims import CFG, DictLookup
from tests.test_engine import run

SHARED_ID = "SHARED-1"
ORG = "org_test_evkey"


def _lost_line(org: str = "org_test") -> Charge:
    return charge(
        "LOST-1",
        charge_type=ChargeType.LOST_INBOUND,
        report_type=ReportType.INVENTORY_ADJUSTMENT,
        amount="0.00",
        posted=date(2026, 6, 19),
        org=org,
    )


def _pair(org: str = "org_test") -> tuple[EvidenceRecord, EvidenceRecord]:
    prep = prep_all_pass(SHARED_ID, org=org)
    ret = record(
        SHARED_ID,
        agent="returns",
        fba_shipment_id=None,
        captured=datetime(2026, 6, 29, tzinfo=UTC),
        checks=[check("identity_match", "PASS")],
        org=org,
    )
    return prep, ret


def test_evidence_citation_must_name_its_pod_and_charge_citation_must_not():
    with pytest.raises(ValidationError):
        Citation(kind="evidence", id="PRP-1", content_hash="a" * 64, role="supports")
    with pytest.raises(ValidationError):
        Citation(kind="charge", agent="prep", id="L-1", content_hash="a" * 64, role="reimbursement")


def test_engine_cites_two_records_with_the_same_id_from_different_pods():
    prep, ret = _pair()
    d = run(_lost_line(), [prep, ret])
    assert d.rule_id == "R_LOSS_DOUBTFUL"
    cited = {(c.agent, c.id): c.role for c in d.citations if c.kind == "evidence"}
    assert cited == {("prep", SHARED_ID): "supports", ("returns", SHARED_ID): "contradicts"}
    by_pod = {c.agent: c.content_hash for c in d.citations if c.kind == "evidence"}
    assert by_pod["prep"] == prep.content_hash and by_pod["returns"] == ret.content_hash
    assert prep.content_hash != ret.content_hash


def test_validator_rejects_a_citation_pointing_at_the_other_pods_record():
    prep, ret = _pair()
    c = _lost_line()
    d = run(c, [prep, ret])
    assert validate(d, c, DictLookup([prep, ret], [c]), CFG) == []
    swapped = d.model_copy(
        update={
            "citations": [
                x.model_copy(update={"agent": "prep" if x.agent == "returns" else "returns"})
                if x.kind == "evidence"
                else x
                for x in d.citations
            ],
            "content_hash": None,
        }
    ).with_hash()
    errors = validate(swapped, c, DictLookup([prep, ret], [c]), CFG)
    assert f"cited record {SHARED_ID} hash mismatch" in errors


def test_attachment_key_depends_on_the_pod():
    a = attachment_key("s", "org", "prep", SHARED_ID, "x.jpg")
    b = attachment_key("s", "org", "returns", SHARED_ID, "x.jpg")
    assert a != b and len(a) == len(b) == 64


def test_same_record_id_in_two_pods_is_stored_twice_and_each_citation_resolves(app_engine, loaded):
    prep, ret = _pair(ORG)
    c = _lost_line(ORG)
    with org_session(app_engine, ORG) as s:
        fid = repo.upsert_ingest_file(s, ORG, "evkey.csv", "c" * 64, "fee_report")
        repo.insert_charges(s, [c], fid)
        src = SourceRef(file_sha256="d" * 64, row=1, raw={})
        n = repo.insert_records(
            s, [prep, ret], {("prep", SHARED_ID): src, ("returns", SHARED_ID): src}, fid
        )
        assert n == 2
        # Re-inserting is idempotent on (org, agent, record_id).
        again = repo.insert_records(
            s, [prep, ret], {("prep", SHARED_ID): src, ("returns", SHARED_ID): src}, fid
        )
        assert again == 0
        got_prep = repo.get_record(s, "prep", SHARED_ID)
        got_ret = repo.get_record(s, "returns", SHARED_ID)
        assert got_prep == prep and got_ret == ret
        assert repo.get_record(s, "pack", SHARED_ID) is None

    (d,) = run_org(app_engine, ORG, AS_OF).decisions
    assert d.status == RecordStatus.FINAL and d.rule_id == "R_LOSS_DOUBTFUL"
    assert d.decision == Decision.REVIEW
    assert {(x.agent, x.id) for x in d.citations if x.kind == "evidence"} == {
        ("prep", SHARED_ID),
        ("returns", SHARED_ID),
    }


class _WrongPodLookup(DictLookup):
    """A store that answers a (pod, id) lookup with another pod's record of the same id."""

    def evidence(self, agent: str, record_id: str) -> StoredRecord | None:
        other = "returns" if agent == "prep" else "prep"
        return self.records.get((other, record_id))


def test_validator_fails_closed_if_the_store_returns_another_pods_record():
    prep, ret = _pair()
    c = _lost_line()
    d = run(c, [prep, ret])
    errors = validate(d, c, _WrongPodLookup([prep, ret], [c]), CFG)
    assert f"cited record {SHARED_ID} resolved to another record" in errors
