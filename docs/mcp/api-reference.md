# MCP API Reference

Derived from `packages/protocol-schemas/schemas/kicad-mcp-server-info.schema.json` and
`compatibility.yaml`; update this page whenever either public contract changes.

## Current Contract

| Surface | Value |
| --- | --- |
| MCP protocol version | `2026-07-28` |
| Tool schema version | `1.0` |
| Server-info schema version | `1.3.0` |
| Registry schema version | `2025-12-11` |
| Server package version | `3.28.0` |

## Server Info Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | yes |  |
| `server` | object | yes |  |
| `description` | string | no |  |
| `localizedDescriptions` | object | no |  |
| `version` | string | yes |  |
| `mcpProtocolVersion` | string | yes |  |
| `toolSchemaVersion` | string | yes |  |
| `compatibilityRange` | object | yes |  |
| `transport` | object | yes |  |
| `kicad` | object | yes |  |
| `operatingMode` | object | yes |  |
| `capabilities` | object | yes |  |
| `diagnostics` | array | yes |  |

## Capability Fields

| Capability | Type | Description |
| --- | --- | --- |
| `fileBackedDrc` | boolean |  |
| `fileBackedErc` | boolean |  |
| `fileBackedExports` | boolean |  |
| `livePcbRead` | boolean |  |
| `livePcbWrite` | boolean |  |
| `liveSchematicRead` | boolean |  |
| `liveSchematicWrite` | boolean |  |
| `liveEditingTools` | object |  |
| `chatgptConnectorCompatible` | boolean |  |
| `adapterRouting` | object | Deterministic active adapter selection by routed tool category. |
| `cliExports` | object |  |

## Release-Gated MCP Tools

| Gate | Tool |
| --- | --- |
| required | `kicad_get_version` |
| required | `kicad_get_project_info` |
| required | `kicad_set_project` |
| required | `sch_get_symbols` |
| required | `pcb_get_board_summary` |
| required | `export_gerber` |
| required | `export_drill` |
| required | `export_manufacturing_package` |
| optional | `variant_list` |
| optional | `variant_set_active` |
| optional | `export_odb` |
| optional | `pcb_export_3d_pdf` |
| optional | `dfm_run_manufacturer_check` |

## Protocol rollout status

### Current public contract

The primary supported and advertised public MCP contract is `2026-07-28`. `server.json` and generated server information advertise that version first while retaining `2025-11-25` for backward-compatible initialize-based clients.

### Native MCP 2026 strict conformance lane

The historical `2026-07-28-rc` selector remains available as a strict stateless conformance mode on top of the same native SDK v2 final `2026-07-28` path. It covers per-request protocol/client metadata, `Mcp-Method`, `Mcp-Name`, direct `server/discover`, stateless tool/prompt/resource requests, SDK-native negotiation errors, `resultType`, and reviewed cache metadata without a request/response translation bridge.

Tasks and Apps remain explicitly excluded from advertised capabilities. Unsupported extension registration fails closed at server construction, and the discovery contract contains no `extensions` capability. Public metadata now advertises `2026-07-28` as primary and `2025-11-25` as the backward-compatible legacy protocol under [ADR-0006](../adr/0006-mcp-2026-stateless-compatibility-lane.md).
