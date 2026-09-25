"""The harness refuses to run in any state that would make the eval dishonest, stops before
the agent while a disagreement is unresolved, and runs the real pipeline end to end.

The label files here are synthetic and live in temporary git repositories. No test reads
eval/labels_A.csv or eval/labels_B.csv, and no test runs the agent on the eval set."""

import csv
import os
import subprocess
from collections import Counter
from pathlib import Path

import pytest

import run_eval
from common import REPO_ROOT
from metrics import agreement, build_gold

SHEET = "case_id,charge_line,evidence_summary,label,reason\n1,x,y,,\n2,x,y,,\n3,x,y,,\n"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.org")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "sheet.csv").write_text(SHEET, encoding="utf-8")
    _git(tmp_path, "add", "sheet.csv")
    _git(tmp_path, "commit", "-qm", "sheet")
    monkeypatch.setattr(run_eval, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(run_eval, "SHEET_CSV", tmp_path / "sheet.csv")
    monkeypatch.setattr(run_eval, "LABELS_A", tmp_path / "labels_A.csv")
    monkeypatch.setattr(run_eval, "LABELS_B", tmp_path / "labels_B.csv")
    monkeypatch.setattr(run_eval, "RESOLVED_CSV", tmp_path / "resolved.csv")
    monkeypatch.setattr(run_eval, "REPORT_MD", tmp_path / "REPORT.md")
    # The synthetic sheet stands in for what eval/data produces; its data files are none.
    monkeypatch.setattr(run_eval, "DATA_FILES", [])
    monkeypatch.setattr(run_eval, "build_rows", lambda: _read_rows(tmp_path / "sheet.csv"))

    def must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("the agent must not run in this state")

    monkeypatch.setattr(run_eval, "run_agent", must_not_run)
    return tmp_path


def _labels(repo: Path, name: str, labels: list[str], commit: bool = True) -> None:
    rows = "".join(f"{i},x,y,{lab},because\n" for i, lab in enumerate(labels, start=1))
    (repo / name).write_text("case_id,charge_line,evidence_summary,label,reason\n" + rows)
    if commit:
        _git(repo, "add", name)
        _git(repo, "commit", "-qm", f"add {name}")


def test_refuses_when_label_files_are_missing(repo, capsys):
    assert run_eval.main() == run_eval.EXIT_REFUSED
    assert "labels_A.csv is missing" in capsys.readouterr().err
    assert not (repo / "REPORT.md").exists()


def test_refuses_when_a_label_file_is_not_committed(repo, capsys):
    _labels(repo, "labels_A.csv", ["CLAIM", "REVIEW", "REVIEW"])
    _labels(repo, "labels_B.csv", ["CLAIM", "REVIEW", "REVIEW"], commit=False)
    assert run_eval.main() == run_eval.EXIT_REFUSED
    assert "labels_B.csv is not committed" in capsys.readouterr().err


def test_refuses_when_a_committed_label_file_was_edited_afterwards(repo, capsys):
    _labels(repo, "labels_A.csv", ["CLAIM", "REVIEW", "REVIEW"])
    _labels(repo, "labels_B.csv", ["CLAIM", "REVIEW", "REVIEW"])
    _labels(repo, "labels_B.csv", ["CLAIM", "CLAIM", "REVIEW"], commit=False)
    assert run_eval.main() == run_eval.EXIT_REFUSED
    assert "labels_B.csv has uncommitted changes" in capsys.readouterr().err
    _git(repo, "add", "labels_B.csv")  # staged but not committed is still refused
    assert run_eval.main() == run_eval.EXIT_REFUSED


def test_refuses_blank_labels(repo, capsys):
    _labels(repo, "labels_A.csv", ["CLAIM", "", "REVIEW"])
    _labels(repo, "labels_B.csv", ["CLAIM", "REVIEW", "REVIEW"])
    assert run_eval.main() == run_eval.EXIT_REFUSED
    assert "case 2 has label ''" in capsys.readouterr().err


def test_unresolved_disagreement_reports_agreement_first_and_stops_before_the_agent(repo):
    _labels(repo, "labels_A.csv", ["CLAIM", "REVIEW", "DO_NOT_CLAIM"])
    _labels(repo, "labels_B.csv", ["CLAIM", "DO_NOT_CLAIM", "DO_NOT_CLAIM"])
    assert run_eval.main() == run_eval.EXIT_UNRESOLVED
    report = (repo / "REPORT.md").read_text()
    assert "Raw agreement: **2 of 3 = 0.667**" in report
    assert "Cohen's kappa: **0.500**" in report  # worked out in the next test
    assert "Agent metrics not computed: 1 disagreement(s) are unresolved" in report
    assert "Unresolved: 2" in report
    assert "## 3. Agent results" not in report


def test_kappa_in_the_unresolved_example_is_the_hand_value():
    # A: CLAIM 1, REVIEW 1, DNC 1; B: CLAIM 1, DNC 2. p_o = 2/3.
    # p_e = (1/3)(1/3) + (1/3)(0) + (1/3)(2/3) = 1/3; kappa = (2/3 - 1/3) / (2/3) = 0.5.
    ag = agreement(
        {"1": "CLAIM", "2": "REVIEW", "3": "DO_NOT_CLAIM"},
        {"1": "CLAIM", "2": "DO_NOT_CLAIM", "3": "DO_NOT_CLAIM"},
    )
    assert str(ag.kappa) == "0.500"


def test_refuses_an_uncommitted_resolution_file(repo, capsys):
    _labels(repo, "labels_A.csv", ["CLAIM", "REVIEW", "DO_NOT_CLAIM"])
    _labels(repo, "labels_B.csv", ["CLAIM", "DO_NOT_CLAIM", "DO_NOT_CLAIM"])
    (repo / "resolved.csv").write_text("case_id,gold_label,note\n2,REVIEW,agreed\n")
    assert run_eval.main() == run_eval.EXIT_REFUSED
    assert "resolved.csv is not committed" in capsys.readouterr().err


def test_resolved_disagreements_let_the_agent_run(repo, monkeypatch):
    _labels(repo, "labels_A.csv", ["CLAIM", "REVIEW", "DO_NOT_CLAIM"])
    _labels(repo, "labels_B.csv", ["CLAIM", "DO_NOT_CLAIM", "DO_NOT_CLAIM"])
    (repo / "resolved.csv").write_text("case_id,gold_label,note\n2,REVIEW,agreed\n")
    _git(repo, "add", "resolved.csv")
    _git(repo, "commit", "-qm", "resolve")
    called: list[int] = []

    class Reached(Exception):
        pass

    def reached(*args: object, **kwargs: object) -> None:
        called.append(1)
        raise Reached

    monkeypatch.setattr(run_eval, "run_agent", reached)
    monkeypatch.setenv("EVAL_DATABASE_URL", "postgresql+psycopg://x@localhost/alibi_eval")
    monkeypatch.setenv("EVAL_MIGRATION_DATABASE_URL", "postgresql+psycopg://x@localhost/alibi_eval")
    with pytest.raises(Reached):
        run_eval.main()
    assert called == [1]


def test_refuses_to_reset_a_database_that_is_not_an_eval_database():
    with pytest.raises(run_eval.EvalRefused, match="refusing to reset database 'alibi'"):
        run_eval.prepare_database("postgresql+psycopg://alibi_owner:pw@localhost:5432/alibi")


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is not set; run tests via `make test`")
    return value


def test_agent_run_and_report_end_to_end_on_the_development_sample():
    """Plumbing only: the real pipeline on data/ (not the eval set) in the test database,
    with synthetic gold labels. Not an eval result."""
    data = REPO_ROOT / "data"
    run = run_eval.run_agent(
        _env("TEST_DATABASE_URL"),
        _env("TEST_MIGRATION_DATABASE_URL"),
        report=data / "fee_report_sample.csv",
        upstream=data / "upstream",
    )
    assert len(run.decisions) == 61 and set(run.latency_ms) == set(run.decisions)
    assert Counter(d.decision.value for d in run.decisions.values()) == {
        "REVIEW": 59,
        "DO_NOT_CLAIM": 2,
    }
    ids = sorted(run.decisions)
    labels = {c: run.decisions[c].decision.value for c in ids}
    labels[ids[0]] = "CLAIM"  # one synthetic missed claim
    ag = agreement(labels, dict(labels))
    gold = build_gold(labels, dict(labels), {})
    types = run_eval.charge_types_of(data / "fee_report_sample.csv")
    lab = run_eval.Labels(labels, dict(labels), {}, {})
    report = run_eval.render_report(
        commit="0" * 40, ag=ag, gold=gold, lab=lab, run=run, charge_types=types
    )
    assert "- Charges evaluated: **61**" in report
    assert "missed claims: **1**" in report
    assert "Claim precision: **n/a** (0 of 0)" in report
    assert "REVIEW rate: **0.967** (59 of 61)" in report
    assert "## 4. Failure modes" in report and ids[0] in report
    assert "Model calls: 0" in report
    assert report.count("| agree |") + report.count("| disagree |") == 61


def test_refuses_when_the_data_changed_after_labelling(repo, monkeypatch, capsys):
    _labels(repo, "labels_A.csv", ["CLAIM", "REVIEW", "REVIEW"])
    _labels(repo, "labels_B.csv", ["CLAIM", "REVIEW", "REVIEW"])
    changed = _read_rows(repo / "sheet.csv")
    changed[1]["evidence_summary"] = "Prep record ... FAIL"
    monkeypatch.setattr(run_eval, "build_rows", lambda: changed)
    assert run_eval.main() == run_eval.EXIT_REFUSED
    assert "does not match what eval/data produces now" in capsys.readouterr().err


def test_refuses_when_a_labeller_edited_the_evidence_column(repo, capsys):
    _labels(repo, "labels_A.csv", ["CLAIM", "REVIEW", "REVIEW"])
    _labels(repo, "labels_B.csv", ["CLAIM", "REVIEW", "REVIEW"])
    text = (repo / "labels_B.csv").read_text().replace("2,x,y,", "2,x,y edited,", 1)
    (repo / "labels_B.csv").write_text(text)
    _git(repo, "commit", "-qam", "edit")
    assert run_eval.main() == run_eval.EXIT_REFUSED
    assert "labels_B.csv does not match" in capsys.readouterr().err


def test_refuses_when_a_data_file_is_not_committed(repo, monkeypatch, capsys):
    _labels(repo, "labels_A.csv", ["CLAIM", "REVIEW", "REVIEW"])
    _labels(repo, "labels_B.csv", ["CLAIM", "REVIEW", "REVIEW"])
    data = repo / "fee_report_eval.csv"
    data.write_text("line_id\n1\n")
    monkeypatch.setattr(run_eval, "DATA_FILES", [data])
    assert run_eval.main() == run_eval.EXIT_REFUSED
    assert "fee_report_eval.csv is not committed" in capsys.readouterr().err


def test_a_charge_without_a_decision_fails_the_eval(repo, monkeypatch, capsys):
    _labels(repo, "labels_A.csv", ["CLAIM", "REVIEW", "REVIEW"])
    _labels(repo, "labels_B.csv", ["CLAIM", "REVIEW", "REVIEW"])
    monkeypatch.setattr(run_eval, "run_agent", lambda *a, **k: run_eval.AgentRun({}, {}, 0, 0))
    monkeypatch.setenv("EVAL_DATABASE_URL", "postgresql+psycopg://x@localhost/alibi_eval")
    monkeypatch.setenv("EVAL_MIGRATION_DATABASE_URL", "postgresql+psycopg://x@localhost/alibi_eval")
    assert run_eval.main() == run_eval.EXIT_DROPPED
    assert "no decision for 1, 2, 3" in capsys.readouterr().err
    assert not (repo / "REPORT.md").exists()


def test_false_claim_gate():
    assert run_eval.false_claim_gate(0) == 0
    assert run_eval.false_claim_gate(1) == run_eval.EXIT_FALSE_CLAIMS == 4
