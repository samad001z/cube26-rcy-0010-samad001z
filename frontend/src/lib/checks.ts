// Plain-English names for check keys. The key itself is still shown, in small type, so a
// reviewer can match the page to the stored record.

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

