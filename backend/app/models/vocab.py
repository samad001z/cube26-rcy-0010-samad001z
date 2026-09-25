"""Decision vocabulary (CLAUDE.md). Defined here; used by the engine from Day 2."""

from enum import StrEnum


class Decision(StrEnum):
    CLAIM = "CLAIM"
    DO_NOT_CLAIM = "DO_NOT_CLAIM"
    REVIEW = "REVIEW"


class EvidenceStatus(StrEnum):
    CONTRADICTED = "CONTRADICTED"
    SUPPORTED = "SUPPORTED"
    INSUFFICIENT = "INSUFFICIENT"
    CONFLICTING = "CONFLICTING"


class ReasonCode(StrEnum):
    DUPLICATE_CHARGE = "DUPLICATE_CHARGE"
    ALREADY_REIMBURSED = "ALREADY_REIMBURSED"
    UNRESOLVED_UNIT = "UNRESOLVED_UNIT"
    NO_RELEVANT_EVIDENCE = "NO_RELEVANT_EVIDENCE"
    EVIDENCE_OUTSIDE_WINDOW = "EVIDENCE_OUTSIDE_WINDOW"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


class RecordStatus(StrEnum):
    FINAL = "final"
    PENDING = "pending"
    OVERRIDDEN = "overridden"


class Verdict(StrEnum):
    """Check verdict. UNCERTAIN is not a low-confidence PASS."""

    PASS = "PASS"  # noqa: S105
    FAIL = "FAIL"
    UNCERTAIN = "UNCERTAIN"


class Agent(StrEnum):
    RECEIVING = "receiving"
    PREP = "prep"
    PACK = "pack"
    RETURNS = "returns"
    RECOVERY = "recovery"


class ChargeType(StrEnum):
    INBOUND_DEFECT_FEE = "inbound_defect_fee"
    LOST_INBOUND = "lost_inbound"
    DAMAGED_IN_WAREHOUSE = "damaged_in_warehouse"
    FULFILMENT_FEE_WEIGHT_TIER = "fulfilment_fee_weight_tier"
    REFUND_ISSUED_ITEM_NOT_RETURNED = "refund_issued_item_not_returned"


class ReportType(StrEnum):
    FEE_REPORT = "fee_report"
    INVENTORY_ADJUSTMENT = "inventory_adjustment"
    REIMBURSEMENT_REPORT = "reimbursement_report"
