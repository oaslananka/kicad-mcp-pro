# Schematic Back-Annotation Service Design

## Context

`src/kicad_mcp/tools/schematic.py` still owns four related tools that manage schematic project settings and deferred swap intents:

- `sch_set_hop_over`
- `sch_list_swappable_pins`
- `sch_swap_pins`
- `sch_swap_gates`

These tools combine FastMCP registration with project JSON mutation, symbol-library inspection, candidate validation, and `.kicad-mcp` state persistence. They form a coherent boundary distinct from schematic geometry authoring.

## Decision

Create a FastMCP-free `SchematicBackAnnotationService` in `src/kicad_mcp/schematic/back_annotation.py` and a thin registration adapter in `src/kicad_mcp/tools/schematic_back_annotation.py`.

The service receives explicit callables for:

- active project-file lookup;
- placed-symbol lookup and library-ID parsing;
- pin-alias and unit discovery;
- symbol-library file access;
- `.kicad-mcp` state loading and saving.

The adapter preserves the current tool names, signatures, descriptions, annotations, and headless metadata. `schematic.py` remains the composition root and injects existing helpers into the service.

## Behavior Preservation

The extraction must preserve:

- the exact missing-project and invalid-project JSON errors;
- `hop_over_display` mutation and formatted JSON output;
- numeric-only pin candidates sorted numerically;
- available gate discovery from symbol-library blocks;
- the exact informational note in the swappable-candidates payload;
- invalid pin/gate messages without writing state;
- append-only `pin_swaps.json` and `gate_swaps.json` intent records;
- existing state filenames, payload shapes, and result strings;
- all four tools' `headless_compatible` metadata.

No public tool surface or operating-mode profile changes are permitted.

## Error Handling

The service keeps current fail-fast behavior. Missing symbol references and malformed library IDs continue to propagate through existing injected helpers. Project JSON decode failures are translated to the current `ValueError` messages. Invalid swap candidates return the existing non-exception result strings and do not persist state.

## Architecture Constraints

- The domain module must not import FastMCP, server composition, KiCad connection modules, or `tools.schematic`.
- The adapter may import FastMCP, the service type, and metadata decorators only.
- The adapter `register()` function must remain at or below 300 lines.
- `schematic.py` must contain composition only for these four tools after extraction.

## Verification

Evidence must include:

- direct service tests without FastMCP;
- adapter tests for names, schemas, descriptions, metadata, defaults, validation, and delegation;
- exact full-server surface comparison against `main`;
- unchanged committed tool-surface snapshot;
- focused schematic integration tests;
- architecture boundary checks;
- formatting, Ruff, mypy, scoped Pyright, full unit, coverage, workflow-security, strict documentation, package, security, and representative latency checks.

## Non-Goals

- Applying pin or gate swaps directly to KiCad files;
- changing experimental profile exposure;
- changing state-file formats;
- extracting jumper authoring, pin-label routing, circuit compilation, or rendering tools in this tranche.
