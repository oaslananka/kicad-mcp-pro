# KiCad MCP Pro Cloud service

This directory contains the existing cloud-side TypeScript application, now
maintained alongside the local Python KiCad MCP engine in the same repository.

**Role:** Browser identity, account/device pairing, MCP client authorization,
connection status and remote request routing. Engineering tools execute in the
local KiCad MCP engine; the cloud service does not store native KiCad project
files or provide an AI chat/model runtime.

## Remote AI client setup (development)

When Cloud identity is configured, signed-in users can open **AI connections**
for the exact `PUBLIC_ORIGIN/mcp` endpoint and current ChatGPT and Claude
setup links. The endpoint must be publicly reachable over HTTPS for hosted
AI clients; a localhost development URL cannot be used by a remote host.
Availability and OAuth registration support depend on the specific client
and its workspace configuration. Hosted AI-client authentication has not yet
been accepted against the production deployment.

An account login authorizes only the Cloud account. The owner must also
grant that OAuth client access to an eligible project under **Devices & projects**,
then start the separately enabled local one-shot Connector operation. The
Cloud portal does not proxy arbitrary local tools or store KiCad design
content. Existing account-free local MCP clients remain supported.

## Owner-managed read-only Connector (development; default OFF)

A separate, opt-in `CONNECTOR_MANAGED_READ_ENABLED=true` Cloud mode permits
serial `project_summary` reads over an authenticated device WebSocket, without
asking the owner to approve each read. It requires the existing signed WSS
transport, built-in identity and device pairing; it does **not** coexist with
the per-read approval or manual one-shot modes. It is not deployed by default.

The signed-in owner controls a separate per-project **Turn Connector On / Off**
switch under **Devices & projects**. Missing database switch rows are OFF; enabling checks
enrolled device and read-only project ownership. The usual OAuth client/project
grant, access-token revocation and signed device session checks remain
mandatory **for every read**; disabling access discards in-flight results.
No arbitrary native commands, project content, local paths or private keys
cross this interface.

This is **Cloud-side protocol/owner-control groundwork**. A durable local
Connector with automatic reconnect, restart recovery and native current-device
acceptance is not yet complete. A Cloud test passing does not demonstrate an
end-to-end continuously running local client.

## Device connection status

The signed-in **Devices** page shows whether the device has a currently
authenticated, open Cloud Connector WebSocket session. It is scoped to the
current account, updates when the page is refreshed, and does not imply KiCad
GUI/IPC availability or permission to operate on a project. An enabled
device with no open session is shown as disconnected; if the Connector service
is disabled, the portal does not claim to know whether a device is online.
No periodic device polling or database status table is required.

## One-command Cloud onboarding (after the unified CLI release)

Users can start with the existing KiCad MCP Pro installation rather than
manually copying OAuth keys or editing application configuration:

```sh
kicad-mcp-pro cloud login
kicad-mcp-pro cloud connect --alias "My workstation"
kicad-mcp-pro cloud status
# Optional, only after registering exactly one local project:
kicad-mcp-pro cloud enable
# Revoke local permission and stop the background service:
kicad-mcp-pro cloud disable
```

`cloud login` opens the **first-party website in the system browser**. Users
choose Google or GitHub if that provider has been configured in Cloud; first-time
social sign-in also creates the Cloud account. The browser session is **not**
misrepresented as a locally stored CLI OAuth access token. On headless/SSH
machines, use `cloud login --no-browser` and open the displayed HTTPS link on
the computer where you want to sign in.

`cloud connect` uses the existing five-minute, signed, one-use device
enrollment: it opens a first-party approval link; a signed-out browser can
complete Google/GitHub sign-in and return automatically to the exact pending
approval page in the **same tab**. The short visible pairing code is kept
temporarily in that tab's session storage, removed after use or expiry, and
never sent as an HTTP query, cookie, OAuth callback value or client secret.
The user must explicitly approve the matching code. The private device key
remains local, and a newly paired device is **disabled** by default. If a
browser blocks same-tab storage or the tab changes, restart pairing rather
than weakening approval checks.

`cloud enable` only starts the optional owner-managed read-only Connector
for one **already registered** project. It does not enable the separate Cloud
Devices-page switch or grant any OAuth client permission. The default local
MCP experience remains account-free and requires no Cloud sign-in.

For production operators, Google sign-in requires a complete
`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` pair and Google provider
redirect registration; GitHub sign-in likewise requires its own complete
provider credentials. The UI lists only configured providers. No additional
identity provider or shared OAuth client is created for this flow.

## Development

Requires Node.js 24 or newer. From this directory:

```sh
npm ci
npm run check
```

The service has its own `package-lock.json` and can be tested or built without
installing the root Python application. Tests that need a PostgreSQL integration
fixture or an external host may be skipped locally; the integration and release
acceptance gates still apply.

Container builds use this directory as the context:

```sh
docker build -f apps/cloud/Dockerfile apps/cloud
```

The existing production service is **not** deployed from this directory merely
because the source was copied here. Switching the production build origin,
database migration ownership and public OAuth endpoint requires a separate,
verified cutover with rollback. Do not treat a local build as deployment
acceptance.

For task-first MCP discovery, `inspect_schematic` selects the schematic
counts tool only if the Cloud operation is enabled and the project grant
is current; it does not remotely list schematic symbols or net names.

For task-first MCP discovery, call `discover_project_workflow` with
`task=inspect_engine`, `check_project_files`, or `check_board_drc`.
The response identifies an actually enabled, project-granted Cloud MCP tool,
or reports the operation unavailable without invoking a local KiCad command.
It never exports raw local tool catalogs, filesystem paths or designs; any
returned operation still requires an explicit owner-started session and
normal project/device authorization. This is task guidance, not a generic
remote tool executor.

With exactly one accessible project, the Cloud MCP presence and DRC-count
pilot tools may omit `project_id`: the Cloud service resolves the sole granted
project and rechecks authorization before routing. If multiple projects are
granted, the AI client must call `list_projects` and supply an explicit
`project_id`. An absent or revoked grant never falls back to a local path.

The independent, default-off `get_project_schematic_counts` operation
uses the local project-bound `sch_get_population_status` MCP tool, but
returns **only** total components, populated, DNP, and BOM counts. The raw
symbol records, component references, local schematic file paths, and design
details remain on the user's machine. It requires the independent Cloud
`CONNECTOR_OPERATOR_SCHEMATIC_COUNTS_ENABLED` flag together with
`CONNECTOR_OPERATOR_ONESHOT_ENABLED`, plus a local owner-started
`--schematic-counts-once` foreground session. It cannot be authorized by
the engine-status, PCB-count, DRC, or presence-only operation.

The separate, default-off `get_project_board_counts` operation exposes
only numeric tracks, vias, footprints, zones, nets, and shapes plus the
`live-gui` or `file-backed` source label. It reuses the existing project-local
`pcb_get_board_summary` tool without forwarding its text, findings, file
paths or design contents. Cloud requires both `CONNECTOR_OPERATOR_ONESHOT_ENABLED`
and `CONNECTOR_OPERATOR_BOARD_COUNTS_ENABLED`; the local owner must start
`--board-counts-once` explicitly for that project. The engine-status,
presence and DRC grants do not authorize this operation.

The separately gated `get_project_engine_status` MCP tool is a manual
**one-shot** outbound Connector test. It requires both
`CONNECTOR_OPERATOR_ONESHOT_ENABLED=true` and
`CONNECTOR_OPERATOR_INSPECTION_ENABLED=true` on the Cloud service, plus a
locally initiated operator-approved `--inspection-once` session. It returns
only engine version, KiCad CLI/IPC availability and four typed
readiness flags (file-backed DRC/ERC and live PCB/schematic read) — never
the raw `kicad_get_server_info` result, native files or local paths.

This is not automatic remote KiCad editing or general MCP tool forwarding.
The existing project-presence and DRC-count-only consent paths cannot enable
this additional operation. Keep the feature off in existing production until
the reviewed connector/device acceptance and separate deployment cutover.

The local stdio/HTTP MCP engine and dashboard remain usable without a cloud
account. Keep project paths on-device and preserve the existing owner/device
authorization checks across remote connections.
