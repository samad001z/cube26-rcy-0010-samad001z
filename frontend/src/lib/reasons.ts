// Short, plain-English headlines for the list's "Why" column, keyed by the engine's rule id
// (backend/app/engine/__init__.py, config/engine.yaml). A headline only restates what the rule
// means; it never adds a fact. The engine's own reason stays on the detail page under
// "Technical detail". A rule missing here falls back to the engine's reason.

type ChargeType =
  | "inbound_defect_fee"
  | "fulfilment_fee_weight_tier"
  | "lost_inbound"
  | "damaged_in_warehouse"
  | "refund_issued_item_not_returned";

interface Headline {
  /** Used for any charge type not listed in `by`. */
  text: string;
  by?: Partial<Record<ChargeType, string>>;
}

const HEADLINES: Record<string, Headline> = {
  R_FILING_WINDOW_NOT_OPEN: { text: "Too early: the window to file a claim hasn't opened yet" },
  R_FEE_REFUND_LINE: { text: "This line is money paid back to you, not a charge" },
  R_ZERO_FEE: { text: "Nothing was charged on this line" },
  R_REIMBURSEMENT_AMBIGUOUS: { text: "A refund could belong to this fee or to another one" },
  R_DUPLICATE: { text: "The same fee was charged twice; this line is the repeat" },
  R_ALREADY_REIMBURSED: { text: "Already paid back in full" },
  R_UNRESOLVED_UNIT: { text: "The charged unit couldn't be matched to any warehouse record" },
  R_EVIDENCE_OUTSIDE_WINDOW: { text: "Warehouse records exist, but none from the time that matters" },
  R_NO_RELEVANT_EVIDENCE: {
    text: "No warehouse record speaks to this charge",
    by: {
      fulfilment_fee_weight_tier: "No weight measurement recorded, so this fee can't be checked",
      inbound_defect_fee: "No prep check recorded that covers this defect",
      lost_inbound: "No prep or return record for this unit",
      damaged_in_warehouse: "No prep record for this unit on this shipment",
      refund_issued_item_not_returned: "No return recorded for this order",
    },
  },
  R_FILING_WINDOW_PASSED: { text: "Too late: the filing deadline has passed" },
  R_CONFLICTING: { text: "Warehouse records disagree with each other" },
  R_INSUFFICIENT: {
    text: "The records can't settle this charge either way",
    by: {
      inbound_defect_fee: "A prep check was unclear or missing, so the fee can't be settled",
      damaged_in_warehouse: "Prep didn't show the unit left in good condition",
      refund_issued_item_not_returned: "A return was recorded, but it can't settle the refund",
      lost_inbound: "The records for this unit can't settle whether it was lost",
    },
  },
  R_AMOUNT_NOT_COMPUTABLE: {
    text: "Evidence backs the claim, but no amount can be worked out yet",
    by: {
      fulfilment_fee_weight_tier: "Measurements exist, but the fee schedule to compare with isn't sourced",
      lost_inbound: "The loss looks real, but there's no unit value on record to claim",
      damaged_in_warehouse: "The unit left prep undamaged, but there's no unit value on record",
      refund_issued_item_not_returned: "A different item came back, but there's no unit value on record",
    },
  },
  R_ITEM_RETURNED: { text: "The customer returned the item complete, so nothing is owed" },
  R_RETURNED_INCOMPLETE_OR_DAMAGED: { text: "The item came back, but incomplete or damaged" },
  R_LOSS_DOUBTFUL: { text: "The 'lost' unit was later returned by a customer" },
  R_SUPPORTED: {
    text: "The records back up the charge",
    by: { inbound_defect_fee: "Prep recorded the defect, so the fee stands" },
  },
  R_PARTIAL_COVERAGE: { text: "The records cover only some of the charged units" },
  R_DEFECT_CATEGORY_MISSING: { text: "Prep checks passed, but Amazon didn't say which defect" },
  R_CONTRADICTED_FULL: {
    text: "The records show this charge is wrong",
    by: { inbound_defect_fee: "Prep shows the defect wasn't there when the unit shipped" },
  },
  R_ENGINE_ERROR: { text: "Couldn't be evaluated (a service failed), so it's kept for review" },
  R_CITATION_INVALID: { text: "The evidence cited couldn't be verified, so it's kept for review" },
};

/** The plain-English headline for a decision, or the engine's reason when none is mapped. */
export function headline(ruleId: string, chargeType: string, engineReason: string): string {
  const h = HEADLINES[ruleId];
  if (!h) return engineReason;
  return h.by?.[chargeType as ChargeType] ?? h.text;
}

export function hasHeadline(ruleId: string): boolean {
  return ruleId in HEADLINES;
}
