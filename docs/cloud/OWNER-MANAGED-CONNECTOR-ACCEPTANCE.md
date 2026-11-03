# Owner-managed Cloud Connector: user acceptance contract

Status: **local implementation and test coverage added; live host/production
acceptance is still pending.** The existing Cloud switch and bounded signed
WSS multi-read path are implemented, but the local persistent Connector must
be installed and accepted on an enrolled device, then exercised against the
currently deployed unified Cloud before this contract is complete.

## The experience

1. Reuse the existing enrolled device and exactly one registered project; no
   second account, OAuth app, domain, pairing or project discovery.
2. The owner enables the local Connector once from their normal user session
   using either `kicad-mcp-pro cloud enable` or the existing command:

   `kicad-mcp-cloud-connector enable`

3. The existing signed-in Cloud Devices page separately enables **Connector On**
   for the registered read-only project. The existing OAuth client/project
   grant remains required. Local activation does not silently turn on the Cloud
   project switch or grant an MCP client access.
4. The local user service resumes at the next user login and keeps one signed
   device WSS session alive. It reconnects after ordinary network failures
   using bounded 15/30/60/120-second backoff plus small jitter.
5. Status is available locally:

   `kicad-mcp-cloud-connector status`

   It reports **Off**, **Connecting**, **Connected**, or **Unavailable**.
   Connected means the enrolled device has an authenticated signed WSS
   session; it does not override the separate Cloud project/client grant.
6. To stop local access:

   `kicad-mcp-cloud-connector disable`

   This removes the local enable marker before stopping the user service,
   so any in-flight local dispatcher authorization check denies subsequent
   work. The Cloud Devices-page switch can also be turned Off independently;
   Cloud checks it and the current OAuth client/project/device grants before
   dispatch and again before returning a result.
7. Disabling either side does not delete the device, key, project registration
   or existing OAuth grant. The owner may deliberately turn the appropriate
   switch back On later.

## Smallest viable technical scope

Reuse the existing device identity, local project registration, owner-private
signing key, Cloud PostgreSQL sessions and per-client OAuth project grants.
No new account, domain, identity provider, cross-repository service, paid
platform, arbitrary remote filesystem access or native KiCad operation.

- **Local:** `kicad_mcp.cloud_managed_connector` is an explicit, default-OFF
  command and user-scoped systemd unit. The unit is installed/enabled only
  after the owner runs `enable`. Without the private local enable marker, the
  service exits before reading the registered identity or loading the device
  signing key. It uses exactly one existing project registration and refuses
  missing, ambiguous, symlinked or incorrectly permissioned records.
- **Cloud:** the existing `CONNECTOR_MANAGED_READ_ENABLED` feature remains
  default-OFF. Its owner Devices-page On/Off switch remains separately
  default-OFF per project. Existing signed-in owner session, CSRF, OAuth
  client/project grant, enrolled device, signed WSS session, enabled project
  and non-revoked device credential checks remain mandatory.
- **Transport:** signed WSS, serial bounded requests (maximum 16 per session),
  ordered acknowledgements and bounded session lifetime. Network recovery
  uses the repository's existing retry policy; no challenge storm or timer
  prompt is introduced.
- **Data:** `project_summary` only: three booleans indicating project, board
  and schematic file presence. No paths, filenames, board/schematic contents,
  secrets, native DRC/ERC, arbitrary commands or general filesystem relay.
- **Revocation:** local enabled marker is checked around local inspection and
  before delivery. Cloud rechecks current OAuth/device/project and managed
  On/Off state before dispatch and before returning results. Turning either
  side Off prevents subsequent results.
- **Trust boundary:** this owner-managed product mode intentionally uses the
  existing enrolled device signing identity plus the normal signed-in Cloud
  owner action and OAuth client/project grants. It is **not** the separate
  stronger independent WebAuthn/owner-consent flow. The stronger
  `cloud_once` and owner-consent paths remain fail-closed; do not weaken or
  substitute them. The existing same-UID/root limitations of owner-private
  device-key access remain: a hostile process with the owner's OS account or
  administrator privileges is outside this local file-permission boundary.

## Acceptance matrix

| Scenario | Required observation |
| --- | --- |
| Fresh install / no local enable marker | Off; no key load or outbound session |
| Enable with one registered project | Existing owner key is used only after explicit local enable |
| Cloud project switch Off | Signed device may be online, but all project reads denied |
| Cloud project switch On plus granted MCP client | Two successive actual presence results on one signed socket |
| Mismatched OAuth client/device/project | Denied; no private path disclosure |
| Network disconnect and recovery | Bounded automatic reconnect; no approval prompts or retry flood |
| User session restart/login while enabled | User service resumes with same registration and scope |
| Local disable while a read is pending | Local authorization fails and no later result is delivered |
| Cloud OAuth client/project grant revoked | In-flight and subsequent read denied |
| Cloud Connector switch turned Off | In-flight and subsequent read denied |
| Corrupt, symlinked or public local grant | Fail closed before signing-key use |
| Native command or arbitrary path request | Denied |
| Socket offline but enable marker exists | Unavailable, not Connected |

## Done means real operation

The code and isolated tests alone do not satisfy product acceptance. Before
leaving the PR DRAFT, exercise the local user service on an already-enrolled
device and the current deployed unified Cloud with the already-granted MCP
client. Verify two real sequential project-presence responses, network
recovery, user-login restart, local Off, Cloud Off and OAuth grant revocation.
Use the normal owner Devices-page control; do not alter production flags or
deploy the Cloud feature as part of local implementation work. Production
activation/deployment requires its separate approval.

The focused Python TLS/managed-read tests and isolated PostgreSQL 17 Cloud CI
are regression evidence, not proof of current production acceptance.
