"""Pure functions for the eval: reading labels, agreement, Cohen's kappa, gold labels and
claim scoring. No I/O beyond reading the label CSVs, no database, no agent."""

import csv
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from common import LABELS


class LabelError(ValueError):
    """A label file is missing a case, has an unknown case or has an invalid label."""


def read_label_rows(path: Path) -> list[tuple[int, str, str, str]]:
    """(row number, case_id, label, reason) from a label file as a spreadsheet exports it.
    Only these three columns are read; every other column (the charge line, the evidence
    summary) is ignored, so re-quoting, re-wrapping or trimming by Google Sheets or Excel
    cannot matter. Tolerates a UTF-8 byte-order mark, CRLF line endings, any quoting,
    header case and spacing, reordered or extra columns, and fully blank rows."""
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = [h.strip().lower() for h in next(reader, [])]
        if "case_id" not in header or "label" not in header:
            raise LabelError(f"{path.name}: needs columns case_id and label")
        wanted = ("case_id", "label", "reason")
        idx = {name: header.index(name) for name in wanted if name in header}

        def cell(row: list[str], name: str) -> str:
            i = idx.get(name)
            return row[i].strip() if i is not None and i < len(row) else ""

        out = []
        for n, row in enumerate(reader, start=2):
            if not any(c.strip() for c in row):
                continue
            out.append((n, cell(row, "case_id"), cell(row, "label"), cell(row, "reason")))
    return out


def read_labels(path: Path, case_ids: Sequence[str]) -> dict[str, str]:
    """case_id -> label for every case in `case_ids`. Refuses blanks, unknown labels,
    unknown or repeated case ids, and missing cases."""
    labels: dict[str, str] = {}
    for n, cid, raw, _reason in read_label_rows(path):
        label = raw.upper().replace(" ", "_")
        if cid in labels:
            raise LabelError(f"{path.name}:{n}: case {cid} appears twice")
        if cid not in case_ids:
            raise LabelError(f"{path.name}:{n}: unknown case {cid!r}")
        if label not in LABELS:
            raise LabelError(
                f"{path.name}:{n}: case {cid} has label {raw!r}; "
                f"expected one of {', '.join(LABELS)}"
            )
        labels[cid] = label
    missing = [c for c in case_ids if c not in labels]
    if missing:
        raise LabelError(f"{path.name}: no label for {len(missing)} case(s): {', '.join(missing)}")
    return labels


def read_resolutions(path: Path, disputed: Sequence[str]) -> dict[str, tuple[str, str]]:
    """case_id -> (gold label, note) from resolved_disagreements.csv. Only disputed cases may
    appear; an absent file means nothing is resolved yet."""
    if not path.exists():
        return {}
    out: dict[str, tuple[str, str]] = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:  # may come from a spreadsheet
        reader = csv.DictReader(fh)
        if reader.fieldnames is not None:
            reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
        if reader.fieldnames is None or not {"case_id", "gold_label"} <= set(reader.fieldnames):
            raise LabelError(f"{path.name}: needs columns case_id, gold_label, note")
        for n, row in enumerate(reader, start=2):
            cid = (row.get("case_id") or "").strip()
            gold = (row.get("gold_label") or "").strip().upper().replace(" ", "_")
            if not cid and not gold:
                continue
            if cid not in disputed:
                raise LabelError(f"{path.name}:{n}: case {cid!r} is not a disagreement")
            if cid in out:
                raise LabelError(f"{path.name}:{n}: case {cid} resolved twice")
            if gold not in LABELS:
                raise LabelError(f"{path.name}:{n}: case {cid} has gold label {gold!r}")
            out[cid] = (gold, (row.get("note") or "").strip())
    return out


def _q(x: Decimal, places: str = "0.001") -> Decimal:
    return x.quantize(Decimal(places), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Agreement:
    n: int
    agreed: int
    raw: Decimal  # agreed / n
    kappa: Decimal | None  # None when chance agreement is 1 (kappa undefined)
    expected: Decimal  # chance agreement p_e
    confusion: dict[tuple[str, str], int]  # (A, B) -> count
    disagreements: list[str]


def agreement(a: Mapping[str, str], b: Mapping[str, str]) -> Agreement:
    """Raw agreement and Cohen's kappa over the cases both labelled.
    kappa = (p_o - p_e) / (1 - p_e), p_e = sum over labels of p_A(label) * p_B(label)."""
    cases = sorted(set(a) & set(b))
    if set(a) != set(b):
        raise LabelError("labellers A and B labelled different cases")
    n = len(cases)
    if n == 0:
        raise LabelError("no labelled cases")
    agreed = sum(1 for c in cases if a[c] == b[c])
    p_o = Decimal(agreed) / n
    ca, cb = Counter(a[c] for c in cases), Counter(b[c] for c in cases)
    p_e = sum(((Decimal(ca[k]) / n) * (Decimal(cb[k]) / n) for k in LABELS), Decimal(0))
    kappa = None if p_e == 1 else _q((p_o - p_e) / (1 - p_e))
    confusion = Counter((a[c], b[c]) for c in cases)
    return Agreement(
        n=n,
        agreed=agreed,
        raw=_q(p_o),
        kappa=kappa,
        expected=_q(p_e),
        confusion=dict(confusion),
        disagreements=[c for c in cases if a[c] != b[c]],
    )


@dataclass(frozen=True)
class Gold:
    labels: dict[str, str]
    notes: dict[str, str]  # resolution notes for disputed cases
    unresolved: list[str]


def build_gold(
    a: Mapping[str, str], b: Mapping[str, str], resolved: Mapping[str, tuple[str, str]]
) -> Gold:
    labels: dict[str, str] = {}
    notes: dict[str, str] = {}
    unresolved: list[str] = []
    for c in sorted(a):
        if a[c] == b[c]:
            labels[c] = a[c]
        elif c in resolved:
            labels[c], notes[c] = resolved[c]
        else:
            unresolved.append(c)
    return Gold(labels, notes, unresolved)


@dataclass
class Score:
    n: int = 0
    claims_recommended: int = 0
    correct_claims: int = 0
    false_claims: int = 0
    missed_claims: int = 0
    gold_claims: int = 0
    review: int = 0
    agree: int = 0
    by_pair: Counter[tuple[str, str]] = field(default_factory=Counter)  # (gold, agent)

    @property
    def claim_precision(self) -> Decimal | None:
        if self.claims_recommended == 0:
            return None
        return _q(Decimal(self.correct_claims) / self.claims_recommended)

    @property
    def claim_recall(self) -> Decimal | None:
        if self.gold_claims == 0:
            return None
        return _q(Decimal(self.correct_claims) / self.gold_claims)

    @property
    def review_rate(self) -> Decimal | None:
        return None if self.n == 0 else _q(Decimal(self.review) / self.n)

    @property
    def accuracy(self) -> Decimal | None:
        return None if self.n == 0 else _q(Decimal(self.agree) / self.n)


def score(gold: Mapping[str, str], agent: Mapping[str, str]) -> Score:
    """Claim metrics over the cases in `gold`. Every gold case must have an agent decision.
    correct claim: agent CLAIM, gold CLAIM. false claim: agent CLAIM, gold not CLAIM.
    missed claim: gold CLAIM, agent not CLAIM."""
    missing = sorted(set(gold) - set(agent))
    if missing:
        raise ValueError(f"no agent decision for {', '.join(missing)}")
    s = Score()
    for c, g in gold.items():
        d = agent[c]
        s.n += 1
        s.by_pair[(g, d)] += 1
        s.agree += g == d
        s.review += d == "REVIEW"
        s.gold_claims += g == "CLAIM"
        if d == "CLAIM":
            s.claims_recommended += 1
            if g == "CLAIM":
                s.correct_claims += 1
            else:
                s.false_claims += 1
        elif g == "CLAIM":
            s.missed_claims += 1
    return s


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile (p in 0..100) of a non-empty sequence."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * p // 100))  # ceil(n * p / 100), at least 1
    return ordered[int(rank) - 1]
