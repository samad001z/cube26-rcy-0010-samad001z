# 11 Demo and Pitch

Product name: **Alibi**. Tagline: "Every charge deserves an alibi."

## 5-minute demo script

**0:00 Problem (30s)**
"Fees land weeks after the event. By then the evidence is scattered across four teams' systems. Sellers either give up the money or file claims they cannot back up. Recovery Manager fixes both."

**0:30 Upload (30s)**
Drop the fee report, reimbursement report and evidence files. Point at the quarantine count: "Three rows had no amount or an invalid date. We quarantine them with reasons. We never guess."

**1:00 Run overview (30s)**
KPIs: charged, claimable, ready, expired, silent, uncertain. "We found X in defensible claims. And we refused to claim Y, and we can tell you why for every one."

**1:30 The contradicted claim (75s)**
Open the packaging-defect charge (the brief's own example). Walk the timeline: prep inspection PRP-000812 PASS at 07:30, handed over at 10:00, fee posted five weeks later. Rule R_CONTRA_FULL. Computation. Citations with hashes. Copy case text. Download claim packet.

**2:45 The refusal (45s)**
Open a SILENT charge: "No Returns record for this order. Here is exactly what evidence would change this." Open an UNCERTAIN one: "Prep says PASS, Receiving logged damage on arrival for the same units. Conflicting evidence. We will not force it."

**3:30 Live re-run (45s)**
Upload the missing Returns data. Re-run. Run diff: four charges moved from SILENT to CONTRADICTED, one to SUPPORTED. "The system gets better as the other Managers feed it, and nothing it already decided changes silently."

**Insert across the demo (if W1-W4 are built; trim other sections to fit 6 min):**
- During the run, keep the Glass Box stream visible: the agent calling tools, rules firing.
- On the contradicted claim, open Cross-examination: "Before we file, a second agent argues Amazon's side. It raised two objections. One was rejected by the verifier, one is pre-answered in the case text."
- Evidence Gaps screen: "This quarter the seller lost 41,200 INR because Returns does not log condition. Recovery tells the other Managers what to capture."
- Download a packet, change one character, drop it on /verify: red. "Anyone can check our claims. Including Amazon."
- Ask Recovery: type "which claims expire this week?" live.

**4:15 Proof (30s)**
Scorecard: false claim rate 0.0% across N generated charges and 18 scenarios, verdict accuracy, amount exactness 100%, injection tests passing. "The LLM parses and writes. It never decides. That is why these numbers are stable."

**4:45 Close (15s)**
"Every claim we file is backed by a record you can click. Every charge we refuse to claim tells you exactly what evidence was missing."

## Architecture slide (one diagram)
The pipeline diagram from `02_ARCHITECTURE.md` with three callouts: keyed retrieval not vector search; rules decide, LLM parses/writes; citation validator gate.

## Judge Q&A prep

**"Where is the AI?"**
In ingestion of messy documents, reason normalisation, notes classification and explanations, all behind validators. Putting an LLM in charge of the verdict would make the system less correct and non-reproducible. The brief's evaluation criteria reward correctness, traceability and conservatism, which are properties of the rules plus validation design.

**"Why not RAG / vector DB?"**
Evidence matching is an exact-key problem. Semantic retrieval returns the sibling SKU's inspection. Our X2 test proves we do not.

**"How do you handle prompt injection?"**
Evidence text is delimited data, the LLM output is constrained to an enum with a verbatim quote, and notes can only produce INDIRECT findings, which alone can never create a claim. Test X9 in CI.

**"How does this integrate with the other four Managers?"**
The EvidenceRecord envelope. Any Manager emitting it plugs in. Show the schema.

**"What happens at scale?"**
Batch retrieval by shipment, indexed keys, stress profile timing on the scorecard.

**"Is the data real?"**
The formats are real (Amazon report headers and reason codes); the evidence is synthetic because this data is private to every seller. The generator writes ground truth, which is what lets us measure accuracy at all. With real data, it enters through adapters and nothing downstream changes.

**"What would you build next?"**
Scheduled SP-API ingestion, human-approved auto-filing, learning which claim types get paid.

## Backup plan
- Recorded video of the full demo.
- Local Docker stack ready if the deployed version is down.
- `LLM_ENABLED=false` mode rehearsed in case the API key rate-limits during judging.
