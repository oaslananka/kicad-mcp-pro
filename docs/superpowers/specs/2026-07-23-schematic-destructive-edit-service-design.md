# Schematic Destructive Edit Service Design

**Status:** Accepted under the approved incremental #434 architecture
**Date:** 2026-07-23
**Tracking issue:** #434

## Context

Three bounded #434 tranches have already extracted read-only inspection, topology inspection, and non-destructive symbol mutation behavior from `src/kicad_mcp/tools/schematic.py`. The next cohesive responsibility is explicit destructive editing: operations that remove schematic nodes or edit label blocks and therefore require careful transaction and structural-loss handling.

## Decision

Create two focused modules:

- `kicad_mcp.schematic.destructive_edit`: a FastMCP-free service containing deterministic wire, symbol, and label edit orchestration behind injected parsing and transaction callables.
- `kicad_mcp.tools.schematic_destructive_edit`: a thin FastMCP adapter preserving public decorators and Pydantic validation.

`tools.schematic.register()` remains the composition root. It injects the existing text parsers, symbol-connection resolver, grid helpers, transaction writer, label-justify helpers, and reload operation.

## Tool Boundary

This tranche moves exactly five public tools:

- `sch_delete_wire`
- `sch_delete_symbol`
- `sch_delete_label`
- `sch_move_label`
- `sch_modify_label`

Authoring, circuit building, rendering, preview, layout, templates, and sheet creation remain future tranches.

## Service Interface

`SchematicDestructiveEditService` receives injected callables for:

- active schematic path resolution and file reading;
- wire extraction, UUID matching, signatures, block extraction, and wire parsing;
- placed-symbol discovery, symbol parsing, symbol connection-point calculation, and coordinate normalization;
- label parsing, grid snapping, snap notices, justify normalization, and justify replacement;
- transactional writes with the existing `allow_node_loss` flag;
- formatting and schematic reload.

The service preserves the existing exact output strings, matching tolerances, first-match behavior, UUID-prefix ambiguity handling, label grid-roundtrip behavior, and transaction flags.

## Structural-Loss Policy

- Wire deletion, symbol deletion, and label deletion continue to call the transaction boundary with `allow_node_loss=True`.
- Label movement and justification changes continue to use the normal structural-loss guard.
- Missing targets remain normal result strings by catching only the existing `ValueError` path.
- Other transaction or parser failures propagate unchanged.

## Dependency Direction

```text
FastMCP
  -> tools.schematic.register
      -> tools.schematic_destructive_edit.register
          -> schematic.destructive_edit.SchematicDestructiveEditService
```

The domain service must not import FastMCP, server/connection state, GUI libraries, or `tools.schematic`.

## Compatibility Rules

- Public names, descriptions, schemas, annotations, profiles, validation, and outputs remain unchanged.
- Existing `DeleteWireInput`, `DeleteSymbolInput`, and `ModifyLabelInput` validation remains in the adapter.
- No transaction, approval, checkpoint, backend-selection, or structural-loss policy changes.
- The committed tool-surface snapshot and generated tool documentation remain unchanged.
- No runtime dependency is added.

## Testing

The tranche requires:

1. direct service tests without FastMCP, including all destructive flags and error branches;
2. adapter tests for exact public contracts and Pydantic validation;
3. existing schematic integration and extended edit tests;
4. unchanged tool-surface and generated-documentation checks;
5. architecture, type, coverage, and representative performance gates.

## Rollout

The PR references #434 and does not close it. The next tranche should extract low-level authoring primitives (`sch_add_symbol`, `sch_add_wire`, `sch_add_label`, power/bus/no-connect tools) as a separate bounded service.
