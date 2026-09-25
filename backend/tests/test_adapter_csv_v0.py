import shutil
from pathlib import Path

import pytest

from app.adapters.csv_v0 import load_config, load_fee_report, load_upstream
from app.core.config import REPO_ROOT
from app.models.vocab import RecordStatus, Verdict

DATA = REPO_ROOT / "data"
SECRET = "test-secret"


@pytest.fixture(scope="module")
def upstream():
    return load_upstream(DATA / "upstream", SECRET)


@pytest.fixture(scope="module")
def fees():
    return load_fee_report(DATA / "fee_report_sample.csv")


def _rec(upstream, record_id):
    return next(r for r in upstream.records if r.record_id == record_id)


def _checks(rec):
    return {c.check_key: c for c in rec.checks}


def test_all_sample_rows_load_with_nothing_quarantined(upstream, fees):
    assert upstream.quarantined == []
    assert fees.quarantined == []
    by_agent: dict[str, int] = {}
    for r in upstream.records:
        by_agent[r.agent] = by_agent.get(r.agent, 0) + 1
    assert by_agent == {"receiving": 100, "prep": 62, "pack": 29, "returns": 24}
    assert len(fees.charges) == 61


def test_every_record_has_a_verifiable_hash_and_contract_fields(upstream):
    for r in upstream.records:
        assert r.verify_hash()
        assert r.schema_version == "csv_v0"
        assert r.client_id == r.organization_id
        assert r.captured_at.tzinfo is not None
        assert r.subject.unit_id.startswith("UNIT-")


def test_loading_twice_gives_identical_hashes_and_keys():
    a = load_upstream(DATA / "upstream", SECRET)
    b = load_upstream(DATA / "upstream", SECRET)
    assert [r.content_hash for r in a.records] == [r.content_hash for r in b.records]
    assert [x.key for x in a.attachments] == [x.key for x in b.attachments]


def test_image_keys_are_not_raw_paths_and_depend_on_secret_and_org(upstream):
    other = load_upstream(DATA / "upstream", "different-secret")
    assert upstream.attachments
    for att in upstream.attachments:
        assert att.source_path not in att.key
        assert "fixtures/" not in att.key
        assert len(att.key) == 64
    assert {a.key for a in upstream.attachments}.isdisjoint({a.key for a in other.attachments})
    for r in upstream.records:
        assert all(i.source_ref is None for i in r.images)


def test_image_keys_unique(upstream):
    keys = [a.key for a in upstream.attachments]
    assert len(keys) == len(set(keys))


def test_prep_mapping_spot_checks(upstream):
    c = _checks(_rec(upstream, "PRP-0003"))
    assert c["polybag_present_sealed"].verdict == Verdict.FAIL
    assert c["suffocation_warning"].verdict == Verdict.PASS
    assert c["fnsku_label_placement"].verdict == Verdict.PASS


def test_prep_not_required_emits_no_check_and_keeps_requirement_flags(upstream):
    rec = _rec(upstream, "PRP-0002")
    keys = _checks(rec).keys()
    assert "polybag_present_sealed" not in keys
    assert "suffocation_warning" not in keys
    assert "expiry_date" not in keys
    assert rec.subject.requirements == {
        "wo_polybag": "False",
        "wo_suffocation_warning": "False",
        "wo_expiry_date": "False",
        "wo_handling_marks": "fragile",
    }
    # PRP-0002's label is on a seam: rule-dependent, so UNCERTAIN with the raw value kept.
    label = _checks(rec)["fnsku_label_placement"]
    assert label.verdict == Verdict.UNCERTAIN
    assert label.detail == "on_seam"


def test_receiving_mapping_spot_checks(upstream):
    c = _checks(_rec(upstream, "RCV-0003"))
    assert c["carton_damage"].verdict == Verdict.FAIL
    assert c["carton_damage"].detail == "crushing"
    assert c["unit_damage"].verdict == Verdict.UNCERTAIN
    assert c["qty_received_matches_ordered"].verdict == Verdict.FAIL
    assert c["qty_received_matches_ordered"].detail == "ordered=48 received=44"
    ok = _checks(_rec(upstream, "RCV-0001"))
    assert ok["qty_received_matches_ordered"].verdict == Verdict.PASS
    assert ok["quality_flags"].verdict == Verdict.PASS


def test_uncertain_is_never_promoted_to_pass(upstream):
    for r in upstream.records:
        for c in r.checks:
            if c.detail == "uncertain":
                assert c.verdict == Verdict.UNCERTAIN


def test_pack_outcome_and_contents(upstream):
    rec = _rec(upstream, "PCK-0006")
    assert rec.outcome is not None
    assert rec.outcome.decision == "seal"
    assert rec.outcome.decided_by == "operator:op_ben"
    assert _checks(rec)["contents_match_order"].verdict == Verdict.PASS
    stops = [r for r in upstream.records if r.outcome and r.outcome.decision == "stop_and_fix"]
    assert len(stops) == 2


def test_returns_pending_review_sets_pending_status(upstream):
    pending = [
        r for r in upstream.records if r.agent == "returns" and r.status == RecordStatus.PENDING
    ]
    assert len(pending) == 1
    assert pending[0].outcome is not None
    assert pending[0].outcome.decision == "pending_review"


def test_charges_ingested_faithfully(fees):
    by_id = {c.line_id: c for c in fees.charges}
    zero = [c for c in fees.charges if str(c.amount) == "0.00"]
    assert len(zero) == 9
    assert by_id["FEE-0003-1"].charge_type == "lost_inbound"
    assert str(by_id["FEE-0002-1"].amount) == "4.25"
    assert by_id["FEE-0003-1"].order_id is None
    assert by_id["FEE-0002-1"].organization_id == "org_demo_alpha"
    assert all(c.source.raw["line_id"] == c.line_id for c in fees.charges)


def test_sample_files_are_untouched():
    import subprocess

    out = subprocess.run(
        ["/usr/bin/git", "status", "--porcelain", "--", "data/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.strip() == ""


def _copy_upstream(tmp_path: Path) -> Path:
    dst = tmp_path / "upstream"
    shutil.copytree(DATA / "upstream", dst)
    return dst


def test_unmapped_value_is_quarantined_not_guessed(tmp_path):
    dst = _copy_upstream(tmp_path)
    f = dst / "prep_sample.csv"
    f.write_text(f.read_text().replace(",not_sealed,", ",banana,", 1))
    res = load_upstream(dst, SECRET)
    assert len(res.quarantined) == 1
    assert "unmapped value 'banana'" in res.quarantined[0].reason
    assert res.quarantined[0].raw["record_id"] == "PRP-0003"
    assert all(r.record_id != "PRP-0003" for r in res.records)
    assert len(res.records) == 100 + 61 + 29 + 24


def test_bad_fee_rows_are_quarantined(tmp_path):
    src = (DATA / "fee_report_sample.csv").read_text().splitlines()
    bad = [
        src[0],
        src[1],
        src[1],  # duplicate line_id
        src[2].replace("lost_inbound", "made_up_fee"),
        src[3].replace("5.10", "abc"),
        src[3].replace("2026-06-23", "not-a-date"),
    ]
    p = tmp_path / "fees.csv"
    p.write_text("\n".join(bad) + "\n")
    res = load_fee_report(p)
    assert len(res.charges) == 1
    assert len(res.quarantined) == 4


def test_config_yaml_yes_no_keys_are_strings():
    cfg = load_config()
    for pod in cfg["pods"].values():
        for spec in pod["enum_checks"]:
            assert all(isinstance(k, str) for k in spec["map"])


def test_optional_defect_category_column(tmp_path, fees):
    # Absent in the sample: every charge has None.
    assert all(c.defect_category is None for c in fees.charges)
    src = (DATA / "fee_report_sample.csv").read_text().splitlines()
    rows = [src[0] + ",defect_category", src[9] + ",label", src[10] + ","]
    p = tmp_path / "fees.csv"
    p.write_text("\n".join(rows) + "\n")
    res = load_fee_report(p)
    assert [c.defect_category for c in res.charges] == ["label", None]
