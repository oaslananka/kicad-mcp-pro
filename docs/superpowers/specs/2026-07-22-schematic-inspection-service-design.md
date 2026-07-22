# Schematic Inspection Service Extraction Design

**Status:** Accepted
**Date:** 2026-07-22
**Tracking issue:** #434

## Context

`src/kicad_mcp/tools/schematic.py` currently combines FastMCP registration,
argument adaptation, file targeting, parsing, domain decisions, formatting, and
mutation behavior. Its `register()` function alone spans more than 3,400 lines.
Issue #434 requires the schematic domain to become independently testable while
preserving every public tool name, schema, annotation, and observable result.

The full extraction is intentionally too large for one reviewable pull request.
This design defines the first bounded tranche: read-only schematic inspection.
Later tranches will apply the same dependency direction to hierarchy,
connectivity, authoring, layout, rendering, and templates.

## Decision

Create two focused modules:

- `kicad_mcp.schematic.inspection`: a FastMCP-free domain service that formats
  schematic inspection results from injected parser and lookup dependencies.
- `kicad_mcp.tools.schematic_inspection`: a composition module that owns the
  public MCP decorators and thin argument adapters for the extracted tools.

The existing `kicad_mcp.tools.schematic.register()` function remains the top-level
composition root during this tranche. It constructs an explicit dependency
bundle and delegates registration to `schematic_inspection.register()`. The new
registration function must remain below 300 lines.

## First-Tranche Tool Boundary

The first tranche moves these public tools without changing their contracts:

- `sch_get_symbols`
- `sch_get_wires`
- `sch_get_labels`
- `sch_get_net_names`
- `sch_get_population_status`
- `sch_get_pin_positions`
- `sch_check_power_flags`

These tools are selected because they are read-only, already deterministic, and
share a coherent inspection responsibility. Mutation and orchestration tools
remain in the current module until later bounded tranches.

## Interfaces

### Domain service

`SchematicInspectionService` receives injected callables for:

- parsing a schematic path;
- adding existing schematic diagnostics to an empty-result message;
- reading population records;
- reading available symbol units;
- calculating symbol pin positions.

Each public operation accepts already validated primitive arguments and returns
the exact text or JSON string currently returned by the MCP tool. It does not
import FastMCP, server state, the schematic registration module, KiCad IPC, or
GUI libraries.

### Registration adapter

`SchematicInspectionDependencies` carries the target resolver and the service.
`tools.schematic_inspection.register(mcp, dependencies)` declares the unchanged
MCP functions and forwards arguments to the service. The existing cache and
headless annotations remain on the same public functions.

## Dependency Direction

Allowed direction:

```text
FastMCP
  -> tools.schematic.register
      -> tools.schematic_inspection.register
          -> schematic.inspection.SchematicInspectionService
```

Forbidden direction:

```text
schematic.inspection -> mcp / server / connection / tools.schematic / kipy / wx
```

The architecture checker will enforce the pure domain boundary and prevent the
new registration adapter from importing the schematic monolith.

## Compatibility Rules

- No tool is added, removed, or renamed.
- Input schemas, descriptions, decorators, cache policy, and annotations remain
  byte-for-byte equivalent at the public tool surface.
- Result text, ordering, numeric formatting, diagnostics, exceptions, and JSON
  formatting remain unchanged.
- The generated tool reference and tool-surface snapshot must not change.
- No new runtime dependency is introduced.

## Error Handling

The service preserves current behavior:

- empty collections return the current diagnostic-enriched messages;
- an explicitly requested missing population reference raises `ValueError`;
- unsupported symbol units return the current human-readable response;
- parser and lookup exceptions propagate exactly as before unless the current
  tool already transforms them.

## Testing

The tranche requires:

1. direct unit tests of the domain service without constructing FastMCP;
2. registration tests proving the seven public tools remain registered with the
   same names, annotations, and schemas;
3. the existing integration tests for schematic behavior;
4. tool-surface snapshot and generated documentation drift checks;
5. architecture, lint, type, coverage, and performance gates.

## Rollout

This pull request references #434 but does not close it. Subsequent bounded
pull requests will extract:

1. sheet hierarchy and connectivity inspection;
2. authoring and transactional mutation services;
3. placement, readability, rendering, and preview services;
4. templates and circuit-building orchestration;
5. final registration decomposition so every schematic registration function is
   at or below 300 lines.
