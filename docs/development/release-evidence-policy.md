# Release-blocking evidence policy — bounded #942 tranche

This tranche is a **pure-domain release policy**, not the final MCP/tool integration.

## Contract

For every `HardwareIntentContract.release_blocking == true` contract, `evaluate_release_evidence()` requires one of:

1. at least one **fresh** exact-contract-revision engineering proof record (`evidence_artifact`, `verification_run`, or `measurement`); or
2. an explicit `ContractWaiver` whose `approval_evidence_ref` resolves to a **fresh** exact-contract-revision `waiver` or `approval` EvidenceRecord.

Anything else blocks release:

- missing proof -> `required_evidence_missing`;
- invalidated proof -> `required_evidence_invalidated`;
- absent freshness assessment / unresolved proof -> `required_evidence_requires_recheck`;
- declared waiver without valid fresh approval evidence -> `waiver_approval_evidence_missing_or_stale`.

Non-release-blocking contracts are intentionally excluded from this hard release gate.

## Safety properties

- Exact contract ID **and revision** are mandatory.
- Duplicate evidence IDs, freshness assessments, or contract revisions are rejected.
- A standalone approval record cannot silently act as engineering proof.
- A stale waiver cannot override stale engineering evidence.
- A fresh engineering proof wins directly; a waiver is only consulted if no fresh proof exists.
- This policy does **not** authenticate human identity or establish append-only waiver history; those remain separate #942 acceptance work.
- This policy does **not** read KiCad files or produce native hashes. It consumes already-verified EvidenceRecord/FreshnessAssessment inputs.

## Local validation

On an isolated Ubuntu checkout based on `main ccc9539f`:

- 11/11 policy tests passed.
- release_evidence_policy.py: **100% statement + branch coverage**.
- full `src/` + `tests/` Ruff lint and format check passed.
- strict mypy for the project passed (321 source modules).
- architecture boundary check passed.

## Remaining before #942 acceptance

The existing `project_release_readiness` and `project_signoff_report` paths in `src/kicad_mcp/tools/validation.py` still need to **consume this policy result** at the actual verdict seam. A later bounded tranche must also provide trusted native/source hash resolution, append-only auditable approval/waiver history and maintained zero stale-evidence escape fixtures.

No automatic issue closure.
