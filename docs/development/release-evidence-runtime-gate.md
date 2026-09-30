# Release evidence runtime gate — bounded #942 tranche

This tranche wires the already-merged fail-closed release evidence policy into
the live project_signoff_report and project_release_readiness decisions.

## Persistence

Project-local adopted metadata uses explicit versioned sidecars:

- .kicad-mcp/hardware_intent_contracts-v1.json
- .kicad-mcp/evidence_records-v1.json

Absence of the contract sidecar preserves legacy projects. Once the contract
sidecar is present, malformed metadata fails closed.

## Current-state resolution

evidence_current_state.py defines deterministic SHA-256 hashing for canonical
GraphEntity.to_dict() payloads and exact comparison against a complete
EvidenceRecord dependency manifest.

A trusted caller may provide a current Engineering Graph and current source
SHA-256. Exact source + dependency hashes yield still_valid; a proven mismatch
yields invalidated; missing project identity, source hash, graph entity, or
dependency hash yields requires_recheck.

The live validation tools in this tranche do not fabricate such a trusted graph.
Until a native current-state resolver is supplied, adopted persisted records are
conservatively requires_recheck.

## Runtime decision

For an adopted release-blocking HardwareIntentContract:

- missing required proof => release FAIL;
- invalidated proof => release FAIL;
- unresolved/recheck proof => release FAIL;
- malformed contract/evidence stores => release FAIL;
- non-release-blocking contracts do not create a hard release veto.

project_signoff_report exposes the contract evidence state and cannot emit PASS
for an unresolved release-blocking contract. project_release_readiness adds the
same blocker to its required_failures/verdict path and approval checklist.

## Non-goals

This tranche does not authenticate approver identity, make waiver history
append-only, or claim zero stale-evidence escapes. It also does not add a
persistent Engineering Graph cache; #944 remains separate.
