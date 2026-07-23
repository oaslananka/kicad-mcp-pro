# Schematic Basic Authoring Service Extraction Design

**Status:** Accepted
**Date:** 2026-07-23
**Tracking issue:** #434

## Context

After the inspection, topology, symbol-mutation, and destructive-edit tranches, `src/kicad_mcp/tools/schematic.py` still owns basic symbol, wire, label, and power-symbol creation inside its FastMCP registration function. These tools share grid snapping, child-sheet targeting, transactional writes, reload ordering, and exact result composition, but their domain behavior remains coupled to FastMCP.

## Decision

Create two focused modules:

- `kicad_mcp.schematic.basic_authoring`: a FastMCP-free service for deterministic symbol, wire, label, and power-symbol creation.
- `kicad_mcp.tools.schematic_basic_authoring`: a thin registration adapter that preserves public decorators and Pydantic validation.

The existing schematic registration function remains the composition root. It injects the current parser, target resolver, symbol-library lookups, formatting helpers, transaction boundary, and reload callback.

## Tool Boundary

This tranche extracts exactly five public tools:

- `sch_add_symbol`
- `sch_add_component`
- `sch_add_wire`
- `sch_add_label`
- `sch_add_power_symbol`

`sch_add_component` remains a public compatibility alias for symbol creation. `sch_add_power_symbol` continues to create a generated `#PWR` reference and delegates through the same symbol-authoring path.

`sch_add_pin_labels`, bus tools, no-connect markers, and higher-level circuit construction remain in later bounded tranches.

## Service Interface

`SchematicBasicAuthoringService` exposes:

```python
add_symbol(..., sheet: str | None, sheet_file: str | None) -> str
add_wire(..., sheet: str | None, sheet_file: str | None) -> str
add_label(..., sheet: str | None, sheet_file: str | None) -> str
add_power_symbol(..., sheet: str | None, sheet_file: str | None) -> str
```

The service receives already validated primitive arguments. The adapter retains Pydantic validation with `AddSymbolInput`, `AddWireInput`, and `AddLabelInput`.

Injected dependencies cover:

- target resolution and target-detail formatting;
- schematic parsing and project-name lookup;
- symbol-library loading, suggestions, and unit discovery;
- grid snapping and snap notices;
- overlap and footprint warnings;
- symbol, wire, and label block construction;
- insertion before sheet instances;
- UUID generation;
- transactional writes and schematic reload.

The service imports no FastMCP, server, connection, GUI, KiCad IPC, or schematic registry module.

## Compatibility Rules

- Preserve all public names, descriptions, schemas, annotations, profiles, defaults, and validation behavior.
- Preserve symbol-not-found suggestions and unsupported-unit messages.
- Preserve library-definition insertion, root UUID selection, project-name selection, overlap warning, footprint warning, and child-sheet targeting.
- Preserve the `name`/`text` label alias and its exact missing-value exception.
- Preserve grid defaults, transaction target paths, reload ordering, and result-line ordering.
- Preserve power-symbol generated references and final placement message.
- Do not add runtime dependencies or change the tool-surface snapshot.

## Error Handling

- Missing symbols return the existing human-readable result without writing or reloading.
- Unsupported units return the existing available-unit result without writing or reloading.
- Missing label `name` and `text` raises the existing `ValueError` before target resolution.
- Transaction, parser, and helper exceptions propagate exactly as before.
- Power-symbol lookup failures return the delegated symbol failure unchanged.

## Architecture Enforcement

The architecture checker will:

- track both new modules;
- keep only the service in `PURE_HELPERS`;
- reject imports from the adapter back into `tools.schematic`;
- enforce a 300-line limit on the adapter `register()` function;
- continue cycle detection across extracted modules.

## Verification

Required evidence:

1. direct service tests without FastMCP;
2. registration tests for exact names, schemas, descriptions, metadata, validation, and delegation;
3. exact full-server metadata comparison against `main`;
4. unchanged tool-surface snapshot and generated tool reference;
5. focused schematic integration tests;
6. full unit, type, coverage, workflow-security, strict documentation, and performance gates.

## Rollout

This is the fifth bounded tranche of #434 and does not close the issue. Later tranches will extract pin-label and bus/marker authoring, circuit compilation/building, placement/readability, rendering/preview, sheet metadata/layout, and template orchestration.
