# Evidence freshness v1 — conservative dependency/fingerprint core (#942)

This first tranche is a pure Python project-domain model; it is **not** a release-signoff authorization. KiCad's native project/solver outputs remain authoritative. The evidence layer records references to verified producer output; it does not reconstruct lost results or assert an unsupported native fact.

## Versioned record

- `EvidenceRecord` v1 has a stable evidence ID, typed kind (`evidence_artifact`, `verification_run`, `measurement`, `approval`, `waiver`), project/source identity, exact SHA-256 source digest, producer/version, explicit UTC capture time, provenance source, a required `dependency_manifest_complete` declaration, and sorted unique SHA-256 digests for named Engineering Graph entities.
- Contract-bound records must carry the exact contract ID/version and include the canonical graph contract entity among explicitly hashed input dependencies. Approval and waiver kinds additionally require that binding; this validates *referential metadata*, not whether a human actually granted approval.
- Checked-in schema `src/kicad_mcp/project/schemas/evidence-freshness-v1.schema.json` is exported using `evidence_record_json_schema()`. Tests verify byte-equivalent parsed runtime vs fixture JSON, strict model serialization, and inclusion of the JSON Schema in the built wheel.
- `attach_evidence_record` validates project key, contract binding, and every declared dependency before adding a typed Engineering Graph node with `depends_on` edges. Repeating the same record is idempotent; attempting to overwrite a different record under the same canonical ID raises. There is no graph-link auto-creation, no silent approval/waiver history rewrite.

## Deterministic three-state evaluation

- `still_valid` requires a complete declared dependency manifest, known mutation scope, evidence record identity matching the stored graph payload both before/after, existing/linked dependencies in both graph states, unchanged relevant graph entities/edges, and the **same exact trusted current input hashes** for all declared dependencies.
- `invalidated` means a definite changed relevant graph entity, dependency edge, or input SHA-256 digest. Unknown facts do not override an already proven invalidation.
- `requires_recheck` means uncertain mutation scope, incomplete manifest, missing graph identity/link, mismatched stored record payload, absent input fingerprint, or project mismatch. This is not a verification PASS.
- The graph impact is compiled from existing `engineering_graph_diff` and `impacted_by` semantics, including before/after dependency edges. It must not create a competing change taxonomy; broad `semantic_intent_diff` alone is **not** proof of freshness.

Seeded fixtures cover USB impedance proof preserved after unrelated U8 component edit, invalidated on stackup or affected USB net geometry edits, invalidated on hash mismatch or dependency-link deletion, and requiring recheck on ambiguity/missing/tampered records. This core requires the caller to supply **authoritative current hashes and a truthful complete dependency declaration**; it does not independently verify KiCad's native oracle or authenticate approvals.

## Explicit remaining #942 work

1. Adapt current `ProjectEditImpactService` / `project_assess_edit_impact` / `project_revalidate_after_edit` to consume this one dependency model without breaking existing text/protocol contracts.
2. Gate project release readiness/signoff against release-blocking contract proof: stale or unresolved evidence cannot lead to approved, except through a separately reviewed waiver policy.
3. Introduce append-only approval/waiver event provenance with authoritative approval identity, version linkage, and replay/audit checks.
4. Create maintained reference-board mutation golden fixtures and machine-readable stale-evidence escape regression report (required target **0**). Validate final CI, quality/security, package and platform gates before closing #942.

Keep #943 native-engine differential canaries, #944 large-project persistent graph cache/journal and #924 SDK-v2 runtime migration as separate changes.
