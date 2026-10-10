# Experimental Provider SDK v0

Issue #945. **Unstable internal interface:** breaking changes are expected; no
public ABI, dynamic loading, marketplace or production provider implementation.
MCP transport remains separate from provider lifecycle and domain state.

## Contract and use

`kicad_mcp.providers` defines typed Part, Solver, Router and Lab Instrument
interfaces, v0 manifests, permission/capability declarations and structured
request/result/provenance envelopes. Providers are explicitly registered from
trusted host code only. Registration rejects adapters whose `ready` and
`invoke` methods are missing, non-callable or not asynchronous, instead of
advertising capabilities that cannot be dispatched. At dispatch, readiness
must return the literal Boolean `True`; `False` means unavailable and a
non-Boolean response is a malformed provider response (never invoked). Domain
callers select by operation and capability, never a vendor name. The versioned,
drift-tested manifest schema is
`src/kicad_mcp/providers/schemas/provider-manifest-v0.schema.json`, generated from
`ProviderManifest.model_json_schema()`.

Calls default to offline with no granted permissions. Non-idempotent calls
require a caller-generated idempotency key; the dispatcher never retries.
External result envelopes, including existing Pydantic model instances, are
revalidated at dispatch; invalid payloads, provenance, and error codes fail
closed as malformed provider results. Existing/copied request models are
revalidated before the host invokes an adapter (an invalid host request raises
a contract validation error), and copied manifest and nested operation models
are revalidated at registration. The independent #942 evidence handoff likewise
rechecks result and manifest models before creating an **unverified** record.
`model_copy(update=...)` and `model_construct(...)` never grant an exemption
from validation at these boundaries.
Timeouts/cancellation do **not** prove that a remote mutation was rolled back.
Read-back and the existing transaction/recovery gates are required before any
retry or engineering release claim.

## Security/threat boundary

- **Code loading:** registration is explicit; arbitrary Python import, entry
  point scanning and untrusted plugins are NOT supported. The SDK provides
  no process sandbox. Only separately reviewed/trusted adapters may run.
- **Network and egress:** both are declared in the manifest. Host entries
  must be exact ASCII DNS-style names or canonical four-octet IPv4 addresses;
  abbreviated, out-of-range, hexadecimal or zero-padded numeric IP forms, URL parts,
  credentials, ports, patterns and malformed labels are rejected. Duplicate
  names are rejected case-insensitively. Offline policy prevents choosing a
  network provider. This is a policy filter, **not** an OS firewall; untrusted
  adapters must be isolated before they can be enabled.
- **Credentials:** never store provider credentials in manifests, request
  payloads, logs or evidence. An approved host adapter owns its secret scope.
- **Permissions:** mutation/instrument control require declared, granted
  privileges. Keep grants operation-scoped and least-privileged.
- **Licensing:** record license and distribution notes; the core does not
  automatically redistribute third-party databases or solver components.
- **Evidence:** provider output is untrusted domain input, not native KiCad
  proof. A handoff emits an unverified #942 measurement record bound to
  explicit host-supplied hashes. Attach it to Engineering Graph v1 and run
  normal evidence freshness and native validation before release decisions.

Residual risk: arbitrary trusted-host code can ignore declarations; no remote
execution security boundary or persisted idempotency journal is promised by v0.
