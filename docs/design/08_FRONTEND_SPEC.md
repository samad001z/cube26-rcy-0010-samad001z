# 08 Frontend Spec

Next.js 15 (app router), TypeScript, Tailwind, shadcn/ui, TanStack Table, Recharts for two small charts. Visual tone: calm ops dashboard, dense tables, monospace for IDs, strong colour coding for verdicts. Accessible contrast.

Verdict colours (tokens): CONTRADICTED green (money back), SUPPORTED slate, SILENT amber, UNCERTAIN violet, DUPLICATE teal, ALREADY_REIMBURSED blue, EXPIRED claim badge red outline.

## Screens

### 1. Data Sources
- Upload zones per file kind. After upload: rows parsed, quarantined count, header mapping table (auto-mapped vs LLM-mapped vs needs confirmation).
- Quarantine drawer: each rejected row with the exact reason.

### 2. Run Overview
- KPI strip: total charged, claimable now, claims READY count, EXPIRED value, SILENT count, UNCERTAIN count.
- Stacked bar: verdict by reason code.
- "Recovery funnel": charged -> evidence found -> contradicted -> claimable -> ready.
- Button: New run. Selector: compare with previous run.

### 3. Charges Table (the main screen)
Columns: charge ID, reason, shipment/order, SKU, amount, verdict chip, coverage %, claimable, confidence, deadline, rule. Filters by verdict/reason/Manager. Search by any ID. Tabs: All, Claims, Needs attention (SILENT + UNCERTAIN), Duplicates, Reimbursed.

The "Needs attention" tab is as prominent as Claims. It is how we visibly score "conservative decision-making".

### 4. Charge Detail (the money shot)
Left: the charge as parsed, with a "view source row" toggle showing the raw row/quote and file hash.
Middle: evidence chain, a vertical timeline: shipment created -> prep inspections -> pack sealed -> handed over -> charge event -> charge posted. Each evidence card shows Manager, record ID, captured_at, the specific check result used, and whether it was inside the custody window. Out-of-window records are shown greyed with the reason.
Right: verdict panel: verdict, rule path (clickable rule ids open the rule description), coverage bar, amount computation lines, citations with hashes, explanation, missing evidence list, case text with copy button, download claim packet.

### 5. Shipment Timeline
Everything known about one shipment across all Managers and all charges on it. Great for the "multiple charges same shipment" scenario.

### 6. Run Diff
Table of charges that changed between two runs with before/after verdict and amount, and which new evidence caused the change.

### 7. Scorecard
Latest eval: per-scenario pass/fail, verdict accuracy, false claim rate, claim recall, amount exactness, citation validity, LLM validator pass rate. This page should be one click from the header. It is our strongest proof.

## Interaction rules
- Every ID anywhere is a link to its detail view.
- Nothing claims more certainty than the backend: UI never recolours or relabels a verdict.
- Empty states explain what data is missing and which upload fixes it.

## Agent and wow screens

### 8. Glass Box (W4)
Live terminal-style stream beside the Run Overview while a run executes: tool calls, rule ids firing, validator results, each line linking to its record. Toggle "agent view" vs "rules view". This is on screen during the demo.

### 9. Ask Recovery (agent chat)
Right-side drawer available on every screen. Suggested prompts. Each answer shows cited record IDs as chips and a collapsible list of tool calls. Unverified answers display "Could not verify" rather than text.

### 10. Cross-examination tab (W1)
On Charge Detail: objections with type, target record/field, UPHELD (red) or REJECTED (grey, with verifier reason), rebuttals. KPI on overview: "N of M claims survived cross-examination".

### 11. Evidence Gaps (W2)
Ranked cards: gap, owning Manager, money at stake, charges affected, example charge links. Small trend chart of fee leakage by reason. Export as a one-page PDF/markdown for the ops team.

### 12. Verify (W3)
Public page, no login. Drop a packet zip; see each check (file hashes, chain segment, signature) turn green or red, and exactly which file was altered.

### Investigator
On SILENT/UNCERTAIN charges: "Investigate" button -> brief with blocking gap, what to request from which Manager, potential value labelled "if evidence is found", deadline.
