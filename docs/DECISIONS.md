# DECISIONS (lightweight ADRs)

### D-001 Rules decide, LLM parses and writes
Status: accepted. Reason: reproducibility, injection resistance, testability. See 06_LLM_LAYER.md.

### D-002 Keyed relational retrieval, no vector store
Status: accepted. Reason: exact entity matching; semantic retrieval causes sibling-SKU false matches.

### D-003 Duplicate charges are claimable
Status: accepted. Reason: the duplicate itself is recoverable; the canonical earlier charge is the evidence.

### D-004 Six verdicts, coverage on CONTRADICTED
Status: accepted. Reason: brief's labels are inconsistent; partial evidence needs a numeric coverage rather than a separate label.

### D-007 Jev for bounded classification, Claude for text and orchestration
Status: accepted. Jev returns calibrated probabilities over options we define and generates no text, so it cannot invent evidence or numbers. Used for L3, L4, objection triage and gap ranking with confidence gates; below the gate we escalate to Haiku or to the conservative outcome. Claude keeps the agent loop, parsing and all text.

### Template
### D-00N Title
Status: proposed/accepted. Context. Decision. Consequences.

### D-005 Tool-using agent over deterministic tools
Status: accepted. Context: the brief asks for an agent; the evaluation rewards correctness and traceability. Decision: the agent orchestrates and explains; verdicts and amounts come only from tools; no tool can set a verdict or amount. Consequences: agent and batch pipeline must produce identical results (CI test).

### D-006 Cross-examiner can only add caution
Status: accepted. The adversarial agent may move READY to NEEDS_REVIEW via verified objections; it can never create or increase a claim.
