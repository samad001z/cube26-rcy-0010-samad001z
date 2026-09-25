"""Shared constants for the held-out eval: paths, the fixed as-of date, and the plain terms
of eval/LABELLING_GUIDE.md. Imports nothing from the decision path (app.engine,
app.precheck, app.pipeline, app.claims): what labellers see must not come from the agent."""

from datetime import date
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
DATA_DIR = EVAL_DIR / "data"
REPORT_CSV = DATA_DIR / "fee_report_eval.csv"
UPSTREAM_DIR = DATA_DIR / "upstream"
SHEET_CSV = EVAL_DIR / "labelling_sheet.csv"
LABELS_A = EVAL_DIR / "labels_A.csv"
LABELS_B = EVAL_DIR / "labels_B.csv"
RESOLVED_CSV = EVAL_DIR / "resolved_disagreements.csv"
REPORT_MD = EVAL_DIR / "REPORT.md"

# Every deadline in the sheet and every agent decision in the eval is judged at this date,
# so labellers and the agent see the same deadline status.
AS_OF = date(2026, 9, 27)

LABELS = ("CLAIM", "DO_NOT_CLAIM", "REVIEW")

# Plain names from the labelling guide, section 4 and section 5.
CHARGE_TYPE_NAMES = {
    "inbound_defect_fee": "Inbound defect fee",
    "fulfilment_fee_weight_tier": "Fulfilment fee (weight tier)",
    "lost_inbound": "Lost inbound",
    "damaged_in_warehouse": "Damaged in warehouse",
    "refund_issued_item_not_returned": "Refund issued, item not returned",
}
TEAM_NAMES = {"receiving": "Receiving", "prep": "Prep", "pack": "Pack", "returns": "Returns"}
FEE_TYPES = {"inbound_defect_fee", "fulfilment_fee_weight_tier"}
