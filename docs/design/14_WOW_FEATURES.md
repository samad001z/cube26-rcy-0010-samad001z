# 14 Wow Features

Everyone will use Claude, GPT or Gemini. Using a strong model is not a differentiator. What stands out is behaviour nobody else thought to build, that a real recovery team would pay for. Four features, in priority order. Build them only after the MUST tier passes its gates.

---

## W1 Cross-Examination ("we argue against ourselves before Amazon does")

**What it is.** Before a claim becomes READY, an adversarial agent plays the marketplace's claims reviewer. It gets the claim packet and read-only tools and tries to reject the claim.

**Why it matters.** Real disputes get rejected for predictable reasons: evidence outside the custody window, wrong scope, no unit valuation, policy exclusions. Catching those before filing is exactly "defensible claims". It also produces a rebuttal paragraph that gets embedded in the case text, pre-answering the objection a human reviewer would raise.

**Output schema**

```python
class ObjectionType(StrEnum):
    OUT_OF_CUSTODY_WINDOW = "OUT_OF_CUSTODY_WINDOW"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"             # evidence for a different sku/unit/carton
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    VALUE_BASIS_MISSING = "VALUE_BASIS_MISSING"   # no unit value source
    LATER_CONTRADICTING_RECORD = "LATER_CONTRADICTING_RECORD"
    FILING_WINDOW = "FILING_WINDOW"
    POLICY_EXCLUSION = "POLICY_EXCLUSION"         # from config/policy_notes.yaml
    OTHER = "OTHER"

class Objection(BaseModel):
    type: ObjectionType
    target_record_id: str | None
    target_field: str | None
    argument: str

class CrossExamination(BaseModel):
    claim_id: str
    objections: list[Objection]
    rebuttals: list[str]      # one per objection the claim survives
```

**How it stays safe.** Every objection type except OTHER maps to a deterministic verifier in `agent/cross_exam_verifiers.py`. A verified objection moves the claim to NEEDS_REVIEW with the objection attached. An unverified objection is shown as "raised, not upheld" with the verifier's reason. OTHER is advisory only. The cross-examiner can never create a claim, raise an amount, or change a verdict. It can only add caution.

**UI.** On the claim detail: a "Cross-examination" tab showing each objection, UPHELD or REJECTED, and the rebuttal. KPI: "claims that survived cross-examination".

**Eval.** Seed 20 claims with planted weaknesses (late evidence, sibling SKU, missing unit cost). Metric: planted weakness detection rate; target 100% for verifiable types. Also: zero READY claims downgraded on clean fixtures (no false alarms on S1).

---

## W2 Evidence Gap ROI ("the price of what you didn't record")

**What it is.** Every SILENT and UNCERTAIN decision already carries `missing_evidence`. Aggregate them into a ranked list of process fixes with a money value.

```
Top evidence gaps this quarter
1. Returns does not log condition on receipt        -> 41,200 INR unrecoverable (23 charges)
2. Prep inspections captured > 14 days before handover -> 18,750 INR at risk (9 charges)
3. Pack does not record carton weight                -> 6,300 INR at risk (4 charges)
```

**How.** Deterministic: group decisions by (missing evidence type, owning Manager), sum `potential_value` from the Investigator's hypothetical-coverage computation. The LLM only writes the one-paragraph summary, validated like explanations. Also show leakage patterns: fee rate by SKU, by reason, by Prep station, trend over time.

**Why it wins.** It turns Recovery Manager from a claims tool into the feedback loop for the other four Managers. For a company building all five, that is the product story. Demo line: "Recovery doesn't just get money back. It tells every other Manager what to capture so next month's money is recoverable."

---

## W3 Tamper-evident claim packets

**What it is.** A claim packet anyone can verify, offline, without trusting our server.

- Audit log is hash-chained: `h_i = sha256(h_{i-1} || canonical_json(event_i))`. Each run stores its head hash.
- Claim packet zip contains: `claim.json`, `case_text.md`, every cited evidence record as canonical JSON, `manifest.json` with sha256 of every file plus the run head hash and the audit events for that charge.
- SHOULD: manifest signed with an Ed25519 key (`cryptography` library); public key published on the Verify page.
- A `/verify` page and a CLI (`python -m recovery.verify packet.zip`) recompute every hash and the chain segment and report VALID or exactly what was altered.

**Demo.** Download a packet, edit one character in an evidence file, drop it on /verify: it shows the tampered file in red. Ten seconds, memorable, and it signals fintech-grade thinking.

---

## W4 Glass Box (live reasoning view)

**What it is.** A live stream (SSE) of the agent's tool calls and every rule firing while a run executes: `resolve_entities(CHG-48291) -> SHP-10291, SKU-9281, 10 units`, `R_CONTRA_FULL fired`, `validate_claim PASS`. Each line links to its record.

**Why.** Judges see the agent working and see that decisions come from rules. It answers "is this just a GPT wrapper?" without you saying a word.

---

## What we are deliberately not building

- A vision component. The brief says this Manager has no camera workflow; adding one signals we did not read it.
- Fine-tuning or training a model. No labelled data exists and it does not serve any requirement.
- Multi-agent debate for verdicts. Non-deterministic and exploitable.

## Build order and time budget

W4 Glass Box is cheap once the audit log exists (half a day). W3 is mostly hashing (half a day, signing optional). W2 is aggregation plus one screen (half a day). W1 is the most valuable and the most work (one day with verifiers and eval). If time is short: W4, W3, W2, then W1 with only the three most common objection types.
