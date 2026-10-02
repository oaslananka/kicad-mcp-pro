# MCP API Reference

Derived from `packages/protocol-schemas/schemas/kicad-mcp-server-info.schema.json` and
`compatibility.yaml`; update this page whenever either public contract changes.

## Current Contract

| Surface | Value |
| --- | --- |
| MCP protocol version | `2025-11-25` |
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

The supported and advertised public MCP contract is `2025-11-25`. `server.json`, generated server information, stable client examples, and the production MCP Python SDK remain aligned to that version.

### Native MCP 2026 canary lane

An opt-in Streamable HTTP canary uses the stable MCP Python SDK v2 native final `2026-07-28` protocol path. It covers per-request protocol/client metadata, `Mcp-Method`, `Mcp-Name`, direct `server/discover`, stateless tool/prompt/resource requests, SDK-native negotiation errors, `resultType`, and reviewed cache metadata without a request/response translation bridge.

The lane explicitly excludes Tasks and Apps extensions from advertised capabilities. Unsupported extension registration fails closed at server construction, and the discovery contract contains no `extensions` capability. `server.json` remains on `2025-11-25`; any public `2026-07-28` promotion is a separate reviewed release decision under [ADR-0006](../adr/0006-mcp-2026-stateless-compatibility-lane.md).
