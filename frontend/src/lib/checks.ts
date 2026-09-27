// Plain-English names for check keys. The key itself is still shown, in small type, so a
// reviewer can match the page to the stored record.

import type { Verdict } from "@/lib/types";

const NAMES: Record<string, string> = {
  // Recovery's own checks on every decision (ARCHITECTURE.md)
  unit_resolved: "The charged unit was found in upstream records",
  not_duplicate: "The charge is not a repeat of an earlier line",
  not_already_reimbursed: "The charge has not already been paid back",
  within_filing_window: "A claim can still be filed (deadline)",
  evidence_present: "Some upstream record speaks to this charge",
  evidence_in_custody_window: "That evidence was recorded at a relevant time",
  evidence_contradicts_charge: "The evidence says the charge is wrong",
  amount_computable: "The amount to claim can be worked out",
  // Upstream pod checks (config/adapters/csv_v0.yaml)
  identity_match: "Right item",
  carton_damage: "Carton undamaged",
  unit_damage: "Unit undamaged",
  polybag_present_sealed: "Polybag present and sealed",
  suffocation_warning: "Suffocation warning present",
  fnsku_label_placement: "FNSKU label placed correctly",
  original_barcode_covered: "Original barcode covered",
  expiry_date: "Expiry date visible",
  handling_marks: "Handling marks present",
  returned_item_condition: "Condition of the returned item",
  parts_complete: "All parts present",
};

export function checkName(key: string): string {
  return NAMES[key] ?? key.replaceAll("_", " ");
}

// What the confidence number means, by verdict. It is how deterministically the engine
// reached THIS verdict (exact comparison or an operator's recorded check), never a chance
// that the outcome is favourable — UNCERTAIN at 1.00 means the engine is certain it could not
// settle the check, not that a PASS was nearly reached. See ARCHITECTURE.md "Routing
// confidence".
const CONFIDENCE_EXPLANATION: Record<Verdict, string> = {
  PASS: "How certain the engine is that this check passed (an exact comparison or an operator's recorded check), not the chance the claim is later accepted.",
  FAIL: "How certain the engine is that this check failed (an exact comparison or an operator's recorded check), not the chance the claim is later accepted.",
  UNCERTAIN:
    "How certain the engine is that it could not settle this check. It is not a probability that the missing answer would have been favourable: UNCERTAIN is not a low-confidence PASS.",
};

export function confidenceExplanation(verdict: Verdict): string {
  return CONFIDENCE_EXPLANATION[verdict];
}
