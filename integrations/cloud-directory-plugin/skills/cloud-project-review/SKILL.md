---
name: cloud-project-review
description: Inspect only explicitly granted KiCad projects through the hosted KiCad MCP Cloud connector, summarizing aggregate board/schematic metadata and availability without editing or exporting designs.
---

# KiCad Cloud Project Review

Use this skill when the user wants to check the availability, connection, or
read-only engineering metadata of a project they have granted to the hosted
KiCad MCP Pro connector.

## Access boundary

- Use the remote kicad-cloud MCP server, not the local stdio server.
- Require the platform's normal OAuth sign-in and the projects:read scope.
- Never request credentials, tokens, local paths, cloud owner secrets, extra
  permissions, or an ungranted project.
- Never interpret a connected device as a live KiCad GUI or authorization to
  mutate the design. This remote surface has no write/export tools.
- If authentication, owner-granted access, or the foreground connector session
  is unavailable, report that state and stop. Do not circumvent it.

## Read-only workflow

1. Call get_service_status to understand active Cloud read capabilities.
2. Call list_projects or list_devices to locate authorized metadata.
   An empty result means no currently granted projects for this client.
3. If there are multiple grants, ask which listed project to inspect. Pass
   only the opaque project ID returned by the server. Use get_project when
   the user requests metadata for a specific granted ID.
4. Use discover_project_workflow to identify an available read-only tool.
   The connector might expose get_project_presence, get_project_drc_counts,
   get_project_engine_status, get_project_board_counts, or
   get_project_schematic_counts; do not call an unavailable capability.
5. Summarize only observed facts, label source/connection readiness, and
   distinguish counts from complete DRC/ERC or manufacturing acceptance.

## Reporting

State which authorized project was selected, which tools ran, which results
were returned, and what could not be checked. Never infer a valid fabrication
package, completed safety signoff, or production-ready PCB from aggregate
counts. Do not suggest or invoke manufacturing orders, exports, or release
actions through the hosted connector.

The packaged skill provides instructions only; the MCP server independently
enforces OAuth, project grants, scope, and operation authorization.
