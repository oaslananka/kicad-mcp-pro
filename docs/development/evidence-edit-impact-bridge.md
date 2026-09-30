# Evidence freshness and existing edit-impact services (#942, stacked tranche)

This tranche builds on draft PR #1002's versioned evidence records. It is not a standalone release signoff. It connects the **existing** `ProjectEditImpactService` to the same `assess_evidence_freshness` compiler through a pure `EvidenceImpactSnapshot` seam, without inventing native KiCad or verification results.

## Host-authority contract

- The host may inject `evidence_snapshot()` into `ProjectEditImpactService`. That callback must supply the **before and after Engineering Graph**, exact current SHA-256 hashes for all declared dependencies, the actual evidence records, and the factual mutation scope. `hashes_authoritative` must remain false until a trusted host has derived these from real project/native inputs.
- When the callback is absent (as in the **current** production MCP registration), the existing `assess()` and `revalidate()` text surfaces include `Evidence freshness: requires_recheck`. They never equate semantic intent equality with evidence PASS. Existing gate re-run taxonomy, tool signatures, and text headings are preserved.
- When a snapshot is injected, `compile_evidence_impact()` delegates to the **same v1 graph/hash classifier**, returning deterministic per-artifact `still_valid`, `requires_recheck`, or `invalidated`; it orders records by ID, refuses duplicate IDs, and propagates definite invalidation. Untrusted hashes or missing evidence cannot be marked valid.
- Selective category gate re-run behavior is unchanged. Unchanged category gates mean only *not re-run*; this is **not** certification of previously produced ERC/DRC, solver or release evidence.

## Acceptance and follow-up

- Isolated Ubuntu verification: 69 related/legacy tests passed; full source/test Ruff format/lint, strict mypy and architecture checks passed. Two new production modules combined coverage 97.47%, bridge alone 100%. This does not substitute for GitHub CI or exact PR patch coverage.
- Before #942 can close, implement a trusted native hash/source resolver and wire it to the MCP registration, extend structured project release-readiness to reject stale or unresolved release-blocking proofs, define auditable append-only approval/waiver history and run a zero stale-evidence escape golden corpus. None of these are claimed by this tranche.
- This is a stacked, **draft** PR targeting `feat/942-evidence-freshness-v1-core` until PR #1002 has merged. Retarget to `main` only after its protected merge and revalidate the resulting diff and checks. Do not merge this child before its parent.
