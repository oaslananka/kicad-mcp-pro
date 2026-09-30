# Release-blocking evidence policy — bounded #942 tranche

This document defines the release-evidence policy and its append-only approval/waiver audit boundary. Runtime signoff and release-readiness integration is provided by the merged #1007 path; the audit store records decision history without becoming an identity provider or native-evidence authority.

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
- This policy does **not** authenticate human identity. Append-only approval/waiver history is handled by the separate `release_approval_audit` store described below.
- This policy does **not** read KiCad files or produce native hashes. It consumes already-verified EvidenceRecord/FreshnessAssessment inputs.

## Append-only approval and waiver history

`src/kicad_mcp/project/release_approval_audit.py` records human approval and waiver decisions in `.kicad-mcp/release_approval_history-v1.db` without modifying historical rows.

The audit store:

- accepts only exact-contract-revision `approval` or `waiver` `EvidenceRecord` values;
- embeds the canonical immutable evidence snapshot and its SHA-256 digest in every event;
- records UTC decision time plus explicit actor, scope, and rationale metadata;
- links events with a SHA-256 predecessor chain and verifies the complete chain before reads or appends;
- installs SQLite triggers that reject `UPDATE` and `DELETE` against historical events; and
- retains old evidence snapshots even after newer decisions are appended, so stale evidence remains auditable rather than being rewritten.

This is an audit trail, not an identity provider. Actor metadata is recorded as supplied and does not itself prove authentication. The release policy still independently requires fresh exact-revision evidence before a release can pass or be treated as explicitly waived.

## Local validation

On an isolated Ubuntu checkout based on `main bb3f546e`:

- 21/21 append-only audit tests passed;
- the audit module has **100% statement + branch coverage**;
- 52 related audit/release-evidence/store/signoff tests passed;
- Ruff and strict mypy passed for the new audit module and tests; and
- the repository architecture boundary check passed.

## Remaining before #942 acceptance

Runtime signoff and release-readiness consume the fail-closed evidence policy via merged #1007. Criterion 7 adds append-only approval/waiver audit history without changing that policy decision path.

The remaining #942 work is maintained zero stale-evidence escape regression evidence plus final epic-wide quality-gate reconciliation. Trusted native/source hash resolution remains a separate capability boundary and must not be fabricated by the audit store.

No automatic issue closure.
