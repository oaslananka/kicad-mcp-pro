# Optional Cloud outbound connector bootstrap (not production enabled)

KiCad MCP Pro remains **fully local-first**. The existing stdio, local HTTP,
desktop and native KiCad workflows do not require a Cloud account or connection.

The separate Cloud backend implements an outbound WebSocket authentication
handshake at `/api/v1/connector/ws`, currently feature-gated off in production.
This repository provides a **manual**, one-shot, outbound-only client for its
two Ed25519 proof-of-possession exchanges. It never receives a KiCad operation,
reads project files, executes DRC/ERC, grants access, enrolls a device, or
starts automatically with the local MCP service or desktop.

## Security / compatibility contract

- Requires the optional `cloud` Python extra; no change to default dependencies.
- User supplies a pre-enrolled canonical UUID, a trusted Cloud owner subject
  and a separately provisioned local Ed25519 PKCS#8 PEM private key.
- Key loading is supported only on POSIX from a **regular owner-owned file**
  with private permissions (mode `0600` or stricter), opened without following
  a final symlink. Keys are neither generated nor uploaded by this client.
  Windows secure credential storage needs a separate implementation.
- WSS is required, using the system-validated TLS certificate chain and
  hostname checking. No browser Origin, authentication headers, query-string
  secrets, compression or proxy fallback is enabled.
- The client verifies strict schema, canonical UUIDs, 256-bit nonces,
  matching device identity, bounded expirations and exact server phase order
  before signing. Server-accepted signatures bind to the expected domains:
  `kicad-cloud-device-handshake-v1` then `kicad-cloud-bound-session-v1`.
- After `connector.ready`, the client sends **no application frames**.
  One run has a bounded five-minute lifetime. There is no unattended
  reconnect loop, background agent or remote command execution.
- Failures never log frame contents, owner subjects, key paths, signatures
  or raw endpoint URLs.

## Manual invocation (only after independently verified device enrollment)

Install from this repository with the explicit optional extra. Once you have
a verified production Cloud device identity and a securely provisioned key:

```shell
kicad-mcp-cloud-connector \
  --wss-url wss://your-verified-cloud-host/api/v1/connector/ws \
  --owner-sub <verified-cloud-owner-subject> \
  --device-id <enrolled-device-uuid> \
  --private-key <secure-owner-controlled-pem-path>
```

The command only attempts authentication. It cannot enroll itself, enable a
device, discover your Cloud owner subject, or access a KiCad project. It
fails closed while the Cloud feature flag remains off.

## Remaining production gates

1. User-controlled device enrollment, safe per-OS private key store/rotation
   and verified desktop lifecycle (Windows key store not yet implemented).
2. Trusted TLS/WebSocket reverse proxy and direct device-to-Cloud live
   interoperability, plus fail-safe reconnection, clock skew, cancellation
   and certificate-error acceptance.
3. Full Google/GitHub owner login, real OAuth client/session validation,
   browser CSRF, rate limiting and Cloud device revocation.
4. Explicit device/project/client-local capability intersection. Read/write
   operations need an independently reviewed dispatch architecture; any
   mutation requires explicit local human approval.
5. Native KiCad DRC/ERC evidence in a controlled test environment.

Do not turn on the Cloud listener or claim end-to-end KiCad acceptance
because these handshake unit tests pass.
