# Schematic Topology Service Extraction Design

**Status:** Accepted
**Date:** 2026-07-23
**Tracking issue:** #434

## Context

PR #443 established a pure schematic inspection service and a thin FastMCP adapter. The next bounded tranche from the accepted #434 rollout is sheet hierarchy and connectivity inspection, which remains embedded in `tools.schematic.register()`.

## Decision

Create:

- `kicad_mcp.schematic.topology.SchematicTopologyService` for deterministic hierarchy and connectivity result construction;
- `kicad_mcp.tools.schematic_topology` for the unchanged FastMCP declarations and argument validation.

The composition root injects the existing schematic loader, diagnostics formatter, connectivity builder, child-sheet iterator, parser, and structured warning callback. The service does not import FastMCP, server state, KiCad connection state, GUI libraries, or the schematic monolith.

## Tool Boundary

This tranche moves four read-only tools:

- `sch_list_sheets`
- `sch_get_sheet_info`
- `sch_get_connectivity_graph`
- `sch_trace_net`

## Compatibility Rules

- Preserve names, signatures, descriptions, schemas, annotations, output strings, ordering, and error transformation.
- Preserve warning emission for hierarchy and sheet-detail loader failures.
- Do not modify connectivity construction, file parsing, child discovery, or any mutation path.
- Do not regenerate the public tool-surface snapshot.
- Keep the new registration function at or below 300 lines.
- Reference but do not close #434.

## Interfaces

`SchematicTopologyService` receives typed callables for:

- loading a schematic object with a sheet manager;
- decorating diagnostic messages;
- building normalized connectivity groups;
- enumerating child-sheet paths;
- parsing a schematic path;
- emitting structured warning events.

Its methods are `list_sheets`, `sheet_info`, `connectivity_graph`, and `trace_net`.

`SchematicTopologyDependencies` carries the active schematic path provider and service. The adapter retains `GetSheetInfoInput` and `TraceNetInput` validation before delegation.

## Testing

- direct service tests without FastMCP;
- registration tests for exact names, schemas, descriptions, validation, and delegation;
- architecture checks for purity, no adapter-to-monolith import, and the 300-line limit;
- existing schematic integration, snapshot, generated docs, type, coverage, security, and performance gates.
