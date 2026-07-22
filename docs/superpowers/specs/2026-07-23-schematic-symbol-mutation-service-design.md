# Schematic Symbol Mutation Service Design

**Status:** Accepted under the approved incremental #434 architecture
**Date:** 2026-07-23
**Tracking issue:** #434

## Context

The first two #434 tranches extracted read-only inspection and topology behavior from `src/kicad_mcp/tools/schematic.py`. The remaining registration function still combines MCP decorators with mutation orchestration. The next bounded tranche addresses non-destructive symbol property and placement mutations while preserving the current backend, transaction, checkpoint, and approval behavior.

## Decision

Create two focused modules:

- `kicad_mcp.schematic.symbol_mutation`: a FastMCP-free service that owns result composition and deterministic move orchestration behind injected callables.
- `kicad_mcp.tools.schematic_symbol_mutation`: a thin registration adapter that owns the unchanged MCP decorators, descriptions, and Pydantic input adaptation.

The existing `tools.schematic.register()` function remains the composition root and injects the current backend functions and text helpers.

## Tool Boundary

This tranche moves exactly four public tools:

- `sch_update_properties`
- `sch_set_dnp`
- `sch_modify_property`
- `sch_move_symbol`

Destructive deletion, wire/label editing, authoring, rendering, layout, and template operations remain separate future tranches.

## Service Interface

`SchematicSymbolMutationService` receives injected callables for:

- backend property updates;
- native DNP updates;
- schematic reload;
- schematic-grid snapping and snap notices;
- transactional writes;
- placed-symbol lookup;
- placed-symbol block shifting.

Service methods return the exact strings currently produced by the public tools. The move method preserves the existing transaction boundary, missing-reference conversion to a result string, reload ordering, coordinate formatting, and optional snap notice.

## Dependency Direction

```text
FastMCP
  -> tools.schematic.register
      -> tools.schematic_symbol_mutation.register
          -> schematic.symbol_mutation.SchematicSymbolMutationService
```

The domain service must not import FastMCP, connection state, backend modules, GUI libraries, or `tools.schematic`.

## Compatibility Rules

- Public names, descriptions, input schemas, annotations, profiles, and output strings remain unchanged.
- `sch_modify_property` remains an observable alias of `sch_update_properties`.
- Existing `MoveSymbolInput` validation remains in the adapter.
- Existing backend selection and transaction/checkpoint behavior remain injected and unchanged.
- No runtime dependency is added.
- The tool-surface snapshot and generated documentation must remain unchanged.

## Error Handling

- Backend property and DNP exceptions propagate exactly as before.
- A missing move reference remains a normal result string rather than an MCP error.
- Transaction failures other than the existing missing-reference `ValueError` continue to propagate.
- Reload is performed only after a successful update or move.

## Testing

The tranche requires:

1. direct service tests without FastMCP;
2. adapter tests for exact names, descriptions, schemas, headless metadata, validation, and delegation;
3. existing schematic integration and population-status tests;
4. unchanged tool-surface and generated-documentation checks;
5. architecture, type, coverage, and representative performance gates.

## Rollout

The PR references #434 and does not close it. The next bounded tranche should handle explicit destructive edits (`sch_delete_wire`, `sch_delete_symbol`, and label deletion/movement) separately because those operations opt into structural node loss and warrant an isolated review.
