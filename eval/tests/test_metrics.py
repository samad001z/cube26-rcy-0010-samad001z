"""Metric functions, checked against small cases worked out by hand."""

from decimal import Decimal
from pathlib import Path

import pytest

from metrics import (
    LabelError,
    agreement,
    build_gold,
    percentile,
    read_labels,
    read_resolutions,
    score,
)

C, R, D = "CLAIM", "REVIEW", "DO_NOT_CLAIM"


def test_cohens_kappa_matches_a_hand_computed_example():
    # 10 cases, 7 agree: p_o = 0.7.
    # A: CLAIM 4, REVIEW 4, DO_NOT_CLAIM 2. B: CLAIM 3, REVIEW 5, DO_NOT_CLAIM 2.
    # p_e = 0.4*0.3 + 0.4*0.5 + 0.2*0.2 = 0.36; kappa = (0.7 - 0.36) / 0.64 = 0.53125.
    a = dict(zip("123456789X", [C, C, C, C, R, R, R, R, D, D], strict=True))
    b = dict(zip("123456789X", [C, C, C, R, R, R, R, D, D, R], strict=True))
    ag = agreement(a, b)
    assert ag.n == 10 and ag.agreed == 7
    assert ag.raw == Decimal("0.700")
    assert ag.expected == Decimal("0.360")
    assert ag.kappa == Decimal("0.531")
    assert ag.disagreements == ["4", "8", "X"]
    assert ag.confusion[(C, R)] == 1 and ag.confusion[(R, D)] == 1 and ag.confusion[(D, R)] == 1


def test_perfect_agreement_is_kappa_one_and_one_label_only_is_undefined():
    a = {"1": C, "2": R, "3": D}
    assert agreement(a, dict(a)).kappa == Decimal("1.000")
    same = {"1": R, "2": R}
    ag = agreement(same, dict(same))
    assert ag.raw == Decimal("1.000") and ag.kappa is None  # p_e = 1


def test_agreement_refuses_different_case_sets():
    with pytest.raises(LabelError):
        agreement({"1": C}, {"2": C})


def _csv(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_read_labels_accepts_the_vocabulary_and_normalises_spacing(tmp_path):
    p = _csv(tmp_path, "l.csv", "case_id,label,reason\n1,claim,x\n2,Do Not Claim,y\n3,REVIEW,\n")
    assert read_labels(p, ["1", "2", "3"]) == {"1": C, "2": D, "3": R}


@pytest.mark.parametrize(
    "body, message",
    [
        ("case_id,label\n1,\n2,CLAIM\n", "has label ''"),
        ("case_id,label\n1,MAYBE\n2,CLAIM\n", "has label 'MAYBE'"),
        ("case_id,label\n1,CLAIM\n", "no label for 1 case"),
        ("case_id,label\n1,CLAIM\n1,REVIEW\n2,CLAIM\n", "appears twice"),
        ("case_id,label\n1,CLAIM\n2,CLAIM\n9,CLAIM\n", "unknown case"),
        ("case,label\n1,CLAIM\n", "needs columns"),
    ],
)
def test_read_labels_refuses_bad_files(tmp_path, body, message):
    with pytest.raises(LabelError, match=message):
        read_labels(_csv(tmp_path, "l.csv", body), ["1", "2"])


def test_gold_is_agreed_labels_plus_resolutions_and_lists_the_rest():
    a = {"1": C, "2": R, "3": D, "4": C}
    b = {"1": C, "2": D, "3": D, "4": R}
    gold = build_gold(a, b, {"2": (R, "prep photo unclear")})
    assert gold.labels == {"1": C, "2": R, "3": D}
    assert gold.notes == {"2": "prep photo unclear"}
    assert gold.unresolved == ["4"]


def test_resolutions_only_for_disputed_cases_and_valid_labels(tmp_path):
    ok = _csv(tmp_path, "r.csv", "case_id,gold_label,note\n4,review,agreed\n")
    assert read_resolutions(ok, ["4"]) == {"4": (R, "agreed")}
    assert read_resolutions(tmp_path / "absent.csv", ["4"]) == {}
    bad = _csv(tmp_path, "b.csv", "case_id,gold_label,note\n1,CLAIM,x\n")
    with pytest.raises(LabelError, match="not a disagreement"):
        read_resolutions(bad, ["4"])
    worse = _csv(tmp_path, "w.csv", "case_id,gold_label,note\n4,YES,x\n")
    with pytest.raises(LabelError, match="gold label"):
        read_resolutions(worse, ["4"])


def test_score_counts_correct_false_and_missed_claims():
    gold = {"1": C, "2": C, "3": R, "4": D, "5": C, "6": R}
    agent = {"1": C, "2": R, "3": C, "4": D, "5": C, "6": R}
    s = score(gold, agent)
    assert (s.n, s.claims_recommended, s.correct_claims) == (6, 3, 2)
    assert (s.false_claims, s.missed_claims, s.gold_claims) == (1, 1, 3)
    assert s.claim_precision == Decimal("0.667")  # 2 of 3
    assert s.claim_recall == Decimal("0.667")
    assert s.review == 2 and s.review_rate == Decimal("0.333")
    assert s.accuracy == Decimal("0.667")  # 4 of 6
    assert s.by_pair[(R, C)] == 1


def test_precision_is_undefined_without_claims_and_missing_decisions_are_refused():
    s = score({"1": R}, {"1": R})
    assert s.claim_precision is None and s.claim_recall is None
    with pytest.raises(ValueError, match="no agent decision"):
        score({"1": R, "2": C}, {"1": R})


def test_nearest_rank_percentile():
    values = [5.0, 1.0, 3.0, 2.0, 4.0]
    assert percentile(values, 50) == 3.0
    assert percentile(values, 95) == 5.0
    assert percentile(values, 0) == 1.0
    with pytest.raises(ValueError):
        percentile([], 50)
