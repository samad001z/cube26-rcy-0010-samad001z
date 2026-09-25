### submissions/samad001z/contract/evidence-record-v0.md:11
This says record IDs are only unique within a pod, while the data model declares them globally unique and uses `record_id` as the evidence table primary key. Two pods could therefore collide and make citations resolve to the wrong record. Make the contract's uniqueness scope match the storage and citation model, or include the pod/manager in every key and lookup.

### submissions/samad001z/design/03_DATA_MODEL.md:95
The contract says `record_id` is only unique within a pod, but the domain model requires it to be globally unique and the database later declares `evidence(record_id pk)`. Two pods can therefore legitimately emit the same ID and collide during ingestion. Either make the contract globally namespaced or use a composite key such as manager plus record_id throughout retrieval and citations.

### submissions/samad001z/design/03_DATA_MODEL.md:103
The hash is defined as the hash of canonical JSON while `content_sha256` is itself part of the EvidenceRecord. That is self-referential, so producers and validators cannot compute a stable agreed value for citations or packet verification. Define the hashed projection explicitly, excluding this field.

### submissions/samad001z/design/03_DATA_MODEL.md:229
The agent and Jev designs emit `AuditEvent(stage="AGENT")` and `AuditEvent(stage="JEV")`, but this enum rejects both values. Implementing either path will fail to serialize the required audit event and break trace reconstruction. Add the stages to the shared model (and any persistence/API enum) before those phases are built.

### submissions/samad001z/design/03_DATA_MODEL.md:240
The production baseline requires a tenant key on every table and every query, but the proposed `files`, `charges`, `evidence`, `runs`, decisions, claims, and audit tables have no `tenant_id`/`org_id` column or tenant-scoped key. An ID-only lookup such as `/api/evidence/{record_id}` can therefore cross organisation boundaries even though the contract mentions `org_id`. Add tenant scoping to the schema, constraints, indexes, and repository queries before exposing these endpoints.

### submissions/samad001z/design/05_DECISION_ENGINE.md:79
This condition is true whenever `claimable` is zero (`reimbursed >= 0`), so every SUPPORTED, SILENT, or UNCERTAIN charge with no claim would be relabelled ALREADY_REIMBURSED. Gate R_REIMBURSED on a positive pre-reimbursement claimable amount before changing the verdict.

### submissions/samad001z/design/07_API_SPEC.md:3
This API contract documents all data and run endpoints without an authentication or tenant context, while the production baseline requires API-key authentication per tenant on every endpoint except health checks. Implementing this spec as written would leave uploads, evidence, and run data vulnerable to cross-tenant access; document and enforce the auth requirement here.

### submissions/samad001z/design/08_FRONTEND_SPEC.md:58
The Verify screen is specified as public and unauthenticated, but the production baseline says every route except `/healthz` requires tenant API-key authentication; the API also exposes this as `POST /api/verify`. This is an unresolved security exception, and packet verification can contain cited evidence from a tenant. Either make verification a local/sanitized operation with an explicit exception, or require authentication and document the tenant boundary.

### submissions/samad001z/design/03_DATA_MODEL.md:99
The v0 contract makes `schema_version`, `org_id`, `unit_id`, per-check `checks`, `verdict`, and `overrides` mandatory envelope fields, but this is the model presented as its implementation and none of those fields are present (identity is only hidden behind an undefined `refs`). An adapter therefore cannot enforce tenant isolation or preserve the contract's check/override data. Add and validate the envelope fields here, or revise the contract and all downstream joins together.

### submissions/samad001z/design/03_DATA_MODEL.md:123
The contract asks Prep for weight and dimensions **per unit**, but these fields are scalar at the record level while `unit_scope` may cover a SKU and quantity. A multi-unit record therefore cannot identify which measurement supports a charged unit; reusing one measurement would create unsupported size-tier claims. Store measurements keyed by `unit_id`, or reject non-unit scopes whenever these measurements are present.

### submissions/samad001z/design/03_DATA_MODEL.md:206
The contract and PR/FAQ promise that reviewer overrides and their reasons are retained, but Claim/Decision and the listed claims table have no override field or audit relation. There is currently nowhere to persist or expose that promised review history, so the claim cannot be audited after an override.

### submissions/samad001z/design/10_BUILD_PHASES.md:19
The P0 prompt has the same path mismatch as the slash commands: it tells the coding agent to read `docs/02_ARCHITECTURE.md` and create `docs/PROGRESS.md`/`docs/DECISIONS.md`, but this submission stores the design pack under `design/`. As a result the first phase will either fail to find its requirements or create a parallel, undocumented docs tree. Make the phase prompts use the actual design paths, or move the whole pack before relying on them.

### submissions/samad001z/design/10_BUILD_PHASES.md:75
This P8 prompt adds L1 PDF/email parsing, but PRD F1 limits v1 ingestion to CSV/XLSX/JSON and the roadmap explicitly puts PDF/email ingestion out of scope. Since P8 is also marked SHOULD, the plan currently directs implementation toward a roadmap feature while contradicting the v1 contract; remove L1 here or update the scope and priority documents together.

