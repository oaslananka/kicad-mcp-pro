# Schematic Hierarchy Authoring Service Design

## Context

`src/kicad_mcp/tools/schematic.py` still owns three related hierarchy-authoring tools:

- `sch_create_sheet`
- `sch_add_hierarchical_label`
- `sch_add_global_label`

They combine FastMCP registration with Pydantic validation, target resolution, grid snapping, child-file creation, kicad-sch-api orchestration, transactional S-expression mutation, reload behavior, and user-facing diagnostics.

## Decision

Create a FastMCP-free `SchematicHierarchyAuthoringService` in `src/kicad_mcp/schematic/hierarchy_authoring.py` and a thin registration adapter in `src/kicad_mcp/tools/schematic_hierarchy_authoring.py`.

The service receives explicit callables for:

- active root schematic lookup and optional child-target resolution;
- grid point snapping and snap diagnostics;
- lazy child-schematic creation and existing schematic loading;
- project-name lookup;
- transactional file writes and reload behavior;
- label-block generation and placement before sheet instances;
- warning emission for dependency and authoring failures.

The adapter preserves existing Pydantic models, aliases, defaults, descriptions, annotations, and public signatures. `schematic.py` remains the composition root and injects current helpers and constants.

## Behavior Preservation

The extraction must preserve:

- lazy handling of a missing `kicad-sch-api` dependency and the exact returned message;
- automatic `.kicad_sch` extension handling;
- creation of parent directories before child-file creation;
- duplicate sheet-name detection before file or root mutation;
- child-sheet creation only when the target file does not exist;
- project-relative forward-slash sheet filenames;
- existing sheet dimensions and project-name propagation;
- exact warning events and user-facing failure strings;
- reload ordering and result formatting;
- `text`/`name` aliases for hierarchical and global labels;
- exact shape, rotation, justify, snap, child-target, transaction, and result behavior.

No public tool surface, profile, backend, or transaction-policy change is permitted.

## Error Handling

Dependency loading remains lazy. Import or factory failures return the current unavailable-dependency string after emitting the current warning event. Sheet authoring exceptions return the current `Could not create child sheet ...` result and warning fields. Label validation and target-resolution errors continue to propagate as they do today.

## Architecture Constraints

- The domain module must not import FastMCP, server composition, KiCad connection modules, or `tools.schematic`.
- The adapter may import FastMCP, existing Pydantic input models, the service type, and metadata utilities only.
- The adapter `register()` function must remain at or below 300 lines.
- `schematic.py` must retain composition wiring only for these tools after extraction.

## Verification

Evidence must include:

- direct service tests without FastMCP;
- adapter tests for names, schemas, descriptions, aliases, defaults, validation, metadata, and delegation;
- exact full-server surface comparison against `main`;
- unchanged committed tool-surface snapshot and generated docs;
- focused hierarchy and schematic integration tests;
- architecture boundary checks;
- formatting, Ruff, mypy, scoped Pyright, full unit, focused coverage, workflow-security, strict documentation, package, security, and representative latency checks.

## Non-Goals

- changing child-sheet serialization or dimensions;
- adding new sheet ports or hierarchical pins;
- changing label rendering defaults;
- extracting pin-label routing, circuit compilation, placement, or rendering tools in this tranche.
