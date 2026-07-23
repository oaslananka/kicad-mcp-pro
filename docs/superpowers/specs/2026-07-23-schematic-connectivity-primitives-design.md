# Schematic Connectivity Primitive Authoring Design

## Context

`src/kicad_mcp/tools/schematic.py` still registers and implements three closely related file-backed authoring tools: `sch_add_bus`, `sch_add_bus_wire_entry`, and `sch_add_no_connect`. They repeat the same target-resolution, grid-snap, transactional append, reload, and response-ordering flow that is already owned by `SchematicBasicAuthoringService` for symbols, wires, and labels.

## Decision

Extend the existing `SchematicBasicAuthoringService` and `schematic_basic_authoring` FastMCP adapter rather than create another service boundary. Bus segments, bus-entry markers, and no-connect markers are basic schematic authoring primitives and share the same injected dependencies and target semantics.

The service will gain:

- `add_bus(...)`
- `add_bus_wire_entry(...)`
- `add_no_connect(...)`

The FastMCP adapter will retain Pydantic validation through `AddBusInput`, `AddBusWireEntryInput`, and `AddNoConnectInput`. `tools.schematic.register()` remains the composition root and injects the existing `wire_block`, plus `bus_entry_block` and `no_connect_block`.

## Compatibility and safety

- Preserve exact public tool names, descriptions, schemas, annotations, profiles, default values, and output ordering.
- Preserve child-sheet targeting through `sheet` and `sheet_file`.
- Preserve 1.27 mm grid-snap behavior and snap notices.
- Preserve the default transaction loss guard; none of these tools opts into structural loss.
- Preserve reload ordering: transactional write first, then schematic reload, then target and snap details.
- Do not add dependencies or change the public tool-surface snapshot.

## Boundaries

`kicad_mcp.schematic.basic_authoring` remains FastMCP-free and imports no registry, server, connection, GUI, KiCad IPC, or SWIG modules. `kicad_mcp.tools.schematic_basic_authoring` remains a thin validation and registration adapter and must keep its `register()` function at or below 300 lines.

## Verification

- Direct service tests cover bus, bus-entry, and no-connect writes, grid coordinates, target path propagation, block construction, response ordering, and transaction flags.
- Registration tests cover exact names, descriptions, schemas, defaults, validation, and argument delegation.
- Full-server metadata for the three tools must match `main` exactly.
- Architecture, tool-surface snapshot, generated docs, focused integration, full unit, type, coverage, workflow-security, strict documentation, and latency benchmark gates must pass.

## Non-goals

- Pin-label routing, jumpers, swap intents, hop-over settings, circuit compilation, or new schematic features.
- Public renaming or schema changes.
- Transaction/checkpoint model changes.
