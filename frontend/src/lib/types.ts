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

/** GET /decisions. `counts` and `facets` describe the whole run; filters narrow `items`. */
export interface DecisionList {
  run: Run | null;
  counts: Partial<Record<DecisionValue, number>>;
  facets: { charge_type?: string[]; rule_id?: string[] };
  filters: { decision?: DecisionValue | null; charge_type?: string | null; rule_id?: string | null };
  items: DecisionSummary[];
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
  integrity_problems: string[];
  earlier_override?: EarlierOverride | null;
  reason: string;
}

/** A human override of the same charge line made on an earlier run (not carried over). */
export interface EarlierOverride {
  record_id: string;
  decision: DecisionValue;
  reviewer: string;
  at: string;
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

/** Where records of this pod can speak to the charge, as the engine used it. End is exclusive. */
export interface CustodyWindow {
  start: string;
  end: string;
  basis: "before_posting" | "after_posting" | "around_posting";
  anchor: "posted_date";
  posted_date: string;
  captured_inside: boolean;
}

export interface Deadline {
  status: "open" | "passed" | "not_yet_open" | "not_verified" | "unknown";
  verdict: Verdict | null;
  detail: string;
}

export interface EvidenceItem {
  record_id: string;
  agent: string;
  usable: boolean;
  why: string;
  cited: boolean;
  captured_at: string | null;
  custody_window: CustodyWindow | null;
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
  /** false when a newer run decided this charge line: older runs are history. */
  overridable: boolean;
  /** Why CLAIM is not offered for this record, or null when it may be chosen. */
  claim_refusal: string | null;
  deadline: Deadline;
  charge: Record<string, unknown> | null;
  evidence: EvidenceItem[];
  line_history: DecisionSummary[];
}
