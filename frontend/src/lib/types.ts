// Shapes returned by the Alibi backend (backend/app/api/review.py). Money and confidence
// arrive as strings (Decimal on the server) and are only ever displayed, never computed on.

export type DecisionValue = "CLAIM" | "DO_NOT_CLAIM" | "REVIEW";
export type Verdict = "PASS" | "FAIL" | "UNCERTAIN";
export type RecordStatus = "final" | "pending" | "overridden";

export interface Run {
  run_id: string;
  decided_at: string;
  charges: number;
  counts: Partial<Record<DecisionValue, number>>;
}

export interface DecisionSummary {
  record_id: string;
  run_id: string;
  line_id: string;
  unit_id: string;
  charge_type: string;
  report_type: string;
  amount_charged: string;
  amount_reimbursed: string;
  currency: string;
  engine_decision: DecisionValue;
  decision: DecisionValue;
  status: RecordStatus;
  evidence_status: string;
  reason_code: string | null;
  rule_id: string;
  confidence: string;
  claim_amount: string | null;
  override_count: number;
  reason: string;
}

export interface Check {
  check_key: string;
  verdict: Verdict;
  confidence: string | null;
  detail: string | null;
  model_version: string | null;
  latency_ms: number | null;
}

export interface Override {
  original_decision: DecisionValue;
  new_decision: DecisionValue;
  reason: string;
  reviewer: string;
  at: string;
}

export interface Claim {
  amount: string;
  currency: string;
  computation: string[];
}

export interface Citation {
  kind: "evidence" | "charge";
  id: string;
  agent: string | null;
  content_hash: string;
  role: string;
  check_keys: string[];
}

export interface DecisionRecord {
  record_id: string;
  organization_id: string;
  subject: {
    line_id: string;
    unit_id: string;
    charge_type: string;
    report_type: string;
    fba_shipment_id: string | null;
    order_id: string | null;
    defect_category: string | null;
    charge_content_hash: string;
  };
  captured_at: string;
  checks: Check[];
  outcome: { decision: DecisionValue; decided_by: string; decided_at: string };
  overrides: Override[];
  status: RecordStatus;
  content_hash: string;
  run_id: string;
  decision: DecisionValue;
  evidence_status: string;
  reason_code: string | null;
  rule_id: string;
  rule_path: string[];
  reason: string;
  warnings: string[];
  next_action: string | null;
  confidence: string;
  coverage: string | null;
  amount_charged: string;
  amount_reimbursed: string;
  currency: string;
  claim: Claim | null;
  citations: Citation[];
  resolved_unit: string | null;
  engine_version: string;
  rules_hash: string;
  config_hash: string;
  model_version: string | null;
}

export interface EvidenceRecordBody {
  record_id: string;
  agent: string;
  captured_at: string;
  operator_label: string | null;
  checks: Check[];
  outcome: { decision: string; decided_by: string; decided_at: string } | null;
  status: string;
  content_hash: string;
  subject: Record<string, string | null>;
}

export interface EvidenceItem {
  record_id: string;
  agent: string;
  usable: boolean;
  why: string;
  cited: boolean;
  hash_at_decision: string;
  hash_matches_decision: boolean;
  record_hash_verifies: boolean;
  record: EvidenceRecordBody | null;
}

export interface OverrideRecord {
  decision_record_id: string;
  line_id: string;
  sequence: number;
  override: Override;
  claim: Claim | null;
  engine_record_hash: string;
  previous_override_hash: string | null;
  content_hash: string;
}

export interface DecisionDetail {
  record: DecisionRecord;
  engine_record: DecisionRecord;
  overrides: OverrideRecord[];
  integrity_problems: string[];
  charge: Record<string, unknown> | null;
  evidence: EvidenceItem[];
  line_history: DecisionSummary[];
}
