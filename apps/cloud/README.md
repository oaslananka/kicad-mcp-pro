# KiCad MCP Pro Cloud service

This directory contains the existing cloud-side TypeScript application, now
maintained alongside the local Python KiCad MCP engine in the same repository.

**Role:** Browser identity, account/device pairing, MCP client authorization,
connection status and remote request routing. Engineering tools execute in the
local KiCad MCP engine; the cloud service does not store native KiCad project
files or provide an AI chat/model runtime.

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

The separately gated `get_project_engine_status` MCP tool is a manual
**one-shot** outbound Connector test. It requires both
`CONNECTOR_OPERATOR_ONESHOT_ENABLED=true` and
`CONNECTOR_OPERATOR_INSPECTION_ENABLED=true` on the Cloud service, plus a
locally initiated operator-approved `--inspection-once` session. It returns
only engine version, KiCad CLI availability and IPC availability — never
the raw `kicad_get_server_info` result, native files or local paths.

This is not automatic remote KiCad editing or general MCP tool forwarding.
The existing project-presence and DRC-count-only consent paths cannot enable
this additional operation. Keep the feature off in existing production until
the reviewed connector/device acceptance and separate deployment cutover.

The local stdio/HTTP MCP engine and dashboard remain usable without a cloud
account. Keep project paths on-device and preserve the existing owner/device
authorization checks across remote connections.
