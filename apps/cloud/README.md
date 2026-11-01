# KiCad MCP Pro Cloud service

This directory contains the existing cloud-side TypeScript application, now
maintained alongside the local Python KiCad MCP engine in the same repository.

**Role:** Browser identity, account/device pairing, MCP client authorization,
connection status and remote request routing. Engineering tools execute in the
local KiCad MCP engine; the cloud service does not store native KiCad project
files or provide an AI chat/model runtime.

## Remote AI client setup (development)

When Cloud identity is configured, signed-in users can open **Connections**
for the exact `PUBLIC_ORIGIN/mcp` endpoint and current ChatGPT and Claude
setup links. The endpoint must be publicly reachable over HTTPS for hosted
AI clients; a localhost development URL cannot be used by a remote host.
Availability and OAuth registration support depend on the specific client
and its workspace configuration. Hosted AI-client authentication has not yet
been accepted against the production deployment.

An account login authorizes only the Cloud account. The owner must also
grant that OAuth client access to an eligible project under **Devices**,
then start the separately enabled local one-shot Connector operation. The
Cloud portal does not proxy arbitrary local tools or store KiCad design
content. Existing account-free local MCP clients remain supported.

## Device connection status

The signed-in **Devices** page shows whether the device has a currently
authenticated, open Cloud Connector WebSocket session. It is scoped to the
current account, updates when the page is refreshed, and does not imply KiCad
GUI/IPC availability or permission to operate on a project. An enabled
device with no open session is shown as disconnected; if the Connector service
is disabled, the portal does not claim to know whether a device is online.
No periodic device polling or database status table is required.

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
