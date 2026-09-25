"""The labelling sheet: built only from ingested records, in the guide's terms, with no
hint of an answer, and held out from data/."""

import csv
import re
import subprocess
import sys
from pathlib import Path

import pytest

import make_sheet
from common import (
    CHARGE_TYPE_NAMES,
    DATA_DIR,
    EVAL_DIR,
    LABELS_A,
    LABELS_B,
    REPO_ROOT,
    SHEET_CSV,
    TEAM_NAMES,
)

GUIDE = (EVAL_DIR / "LABELLING_GUIDE.md").read_text(encoding="utf-8")


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_committed_sheet_is_exactly_what_the_data_produces():
    built = make_sheet.build_rows()
    assert _read(SHEET_CSV) == built
    assert len(built) == 58


def test_every_label_file_covers_the_same_cases_as_the_sheet():
    ids = [r["case_id"] for r in _read(SHEET_CSV)]
    for path in (LABELS_A, LABELS_B):
        assert [r["case_id"] for r in _read(path)] == ids


def test_sheet_label_and_reason_columns_are_empty():
    for r in _read(SHEET_CSV):
        assert r["label"] == "" and r["reason"] == ""


def test_charge_lines_use_the_guide_charge_type_names():
    for name in CHARGE_TYPE_NAMES.values():
        assert name in GUIDE
    for r in _read(SHEET_CSV):
        assert any(r["charge_line"].startswith(n + ";") for n in CHARGE_TYPE_NAMES.values())


def test_records_are_named_by_the_four_guide_teams_only():
    for name in TEAM_NAMES.values():
        assert name in GUIDE
    for r in _read(SHEET_CSV):
        teams = re.findall(r"(\w+) record E-", r["evidence_summary"])
        assert set(teams) <= set(TEAM_NAMES.values()), teams


# Upper-case words allowed in summaries: the guide's three verdicts plus emphasis on
# deadline and record status. Anything else upper-case (CLAIM, REVIEW, SUPPORTED, ...)
# would be agent vocabulary or a hint.
ALLOWED_UPPER = {
    "PASS",
    "FAIL",
    "UNCERTAIN",
    "NOT",
    "YET",
    "OPEN",
    "PASSED",
    "PENDING",
    "UTC",
    "SKU",
}
HINT_WORDS = re.compile(
    r"duplicate|reimbursed|claim(?!s\.)|review|contradict|support|insufficient|conflict"
    r"|should|recover",
    re.IGNORECASE,
)


def test_summaries_use_only_guide_verdicts_and_state_no_outcome():
    for r in _read(SHEET_CSV):
        text = r["evidence_summary"]
        upper = set(re.findall(r"(?<![\w-])[A-Z]{3,}(?![\w-])", text))  # not ids
        assert upper <= ALLOWED_UPPER, (r["case_id"], upper - ALLOWED_UPPER)
        # "claims." only appears in "no known filing deadline for ... claims."
        assert not HINT_WORDS.search(text), (r["case_id"], HINT_WORDS.search(text))
        assert not HINT_WORDS.search(r["charge_line"]), r["case_id"]


DEADLINE = re.compile(
    r"^Deadline: (no known filing deadline for .+ claims\."
    r"|inside the known filing window on \S+; it closes on \S+ .+\."
    r"|filing window NOT YET OPEN on \S+; it opens on \S+ .+\."
    r"|known deadline PASSED on \S+ .+\.)$"
)


def test_every_summary_ends_with_its_deadline_status():
    statuses = set()
    for r in _read(SHEET_CSV):
        last = r["evidence_summary"].splitlines()[-1]
        assert DEADLINE.match(last), (r["case_id"], last)
        statuses.add(last.split(" ")[1])
    # The set covers every deadline status the guide mentions.
    assert statuses == {"no", "inside", "filing", "known"}


DECISION_PATH = (
    "app.engine",
    "app.precheck",
    "app.resolution",
    "app.retrieval",
    "app.pipeline",
    "app.claims",
)


def test_make_sheet_imports_nothing_from_the_decision_path():
    code = (
        "import sys; import make_sheet; "
        f"bad = [m for m in sys.modules if m.startswith({DECISION_PATH!r})]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=EVAL_DIR, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stdout + out.stderr


def _ids(path: Path, cols: tuple[str, ...]) -> set[str]:
    rows = _read(path)
    return {r[c] for r in rows for c in cols if r.get(c)}


def test_eval_set_shares_no_identifier_with_the_development_sample():
    keys = ("line_id", "record_id", "unit_id", "fba_shipment_id", "order_id")
    dev = _ids(REPO_ROOT / "data" / "fee_report_sample.csv", keys)
    for p in (REPO_ROOT / "data" / "upstream").glob("*.csv"):
        dev |= _ids(p, keys)
    ev = _ids(DATA_DIR / "fee_report_eval.csv", keys)
    for p in (DATA_DIR / "upstream").glob("*.csv"):
        ev |= _ids(p, keys)
    assert ev and not (ev & dev)


def test_templates_refuse_to_overwrite_a_label_file_with_labels(tmp_path, monkeypatch):
    a, b = tmp_path / "labels_A.csv", tmp_path / "labels_B.csv"
    a.write_text("case_id,label,reason\nEVL-001,REVIEW,unsure\n", encoding="utf-8")
    monkeypatch.setattr(make_sheet, "LABELS_A", a)
    monkeypatch.setattr(make_sheet, "LABELS_B", b)
    monkeypatch.setattr(make_sheet, "SHEET_CSV", tmp_path / "sheet.csv")
    assert make_sheet.main(["--templates"]) == 1
    assert "EVL-001,REVIEW,unsure" in a.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [LABELS_A, LABELS_B])
def test_label_files_have_the_columns_the_harness_reads(path):
    with path.open(newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert {"case_id", "label", "reason"} <= set(header)
