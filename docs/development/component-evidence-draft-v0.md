# Component evidence draft v0 — issue #946

This is a **review intake record**, not a verified component library or a production
contract. It is intentionally separate from the legacy connectivity seed
`models.component_contracts.ComponentContract` and does not alter #156
`LibraryComponentContractService.verify` or the #942 evidence assessment.

`ComponentEvidenceDraft` records exact manufacturer/MPN identity, source document
revision/hash/location and individual facts with source-local citations. Each
fact explicitly distinguishes a cited value, unknown/not-applicable claim, and
unresolved conflicting sources. Source IDs must exist in the same record; facts,
documents and citations must be unique. A v0 draft can only be `draft` or
`needs_human_review`; it cannot claim `verified`/`approved`, even when source
metadata is syntactically valid. The schema is generated from the model:
`src/kicad_mcp/library/schemas/component-evidence-draft-v0.schema.json`.

The v0 schema verifies **structure only**. Hashes are supplied by the caller and
are not independently recomputed, source citations have not been independently
checked against datasheets, and it does not decide pad/pin/package correctness.
A later trusted review service must check actual source bytes, run existing
symbol/footprint/pin consistency checks, require human verification, and attach
explicit graph dependencies using #942 before promoting any engineering claim.
Do not create fake reviewed components to meet #946 corpus counts.
