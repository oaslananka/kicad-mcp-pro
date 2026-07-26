# Schematic Lifecycle Authoring Service Design

## Context

After PR #462, `src/kicad_mcp/tools/schematic.py::register()` is 469 lines and contains only three nested public tools:

- `sch_add_jumper`
- `sch_annotate`
- `sch_reload`

The tools mix FastMCP registration with small but stateful schematic lifecycle operations. The annotation fixer seam `run_auto_annotate` is separately imported by `tools.fixers` and must remain in the composition module.

## Goal

Move the final nested public schematic tools behind a FastMCP-independent `SchematicLifecycleAuthoringService` and thin adapter without changing their public contracts or behavior.

## Non-goals

- No annotation algorithm or reference ordering changes.
- No jumper naming, snapping, placement, transaction, or reload changes.
- No change to `run_auto_annotate` or fixer imports.
- No composition-root helper split in this PR; that is the following bounded change required to bring `register()` below 300 lines.

## Architecture

Create `src/kicad_mcp/schematic/lifecycle_authoring.py` with three methods:

```python
add_jumper(x_mm, y_mm, pins=2, open_by_default=True, snap_to_grid=True) -> str
annotate(start_number=1, order="alpha") -> str
reload() -> str
```

All parsing, sorting, snapping, block generation, transactional write, reference allocation, reload, and notice helpers are constructor-injected.

Create `src/kicad_mcp/tools/schematic_lifecycle_authoring.py` as the public FastMCP adapter. Preserve:

- exact signatures and docstrings
- `headless_compatible` only on `sch_add_jumper`
- the existing triple `@mcp.tool()` registration seam on `sch_annotate`
- exact schemas, metadata, response strings, exceptions, and annotation enrichment

`tools.schematic` remains the composition root, creates the service, delegates adapter registration, and keeps `run_auto_annotate` available at module scope.

## Dependency boundary

The service imports no FastMCP, connection, GUI, IPC, or schematic registry module. The adapter imports no schematic monolith. Architecture checks enforce both constraints and a 300-line adapter limit.

## Verification

- red-green service and registration tests
- current jumper, annotate, reload, project-library, and fixer integration tests
- exact old/new full-server contract JSON comparison
- architecture, tool-contract, metadata, parity, latency, Ruff, mypy, Pyright, package, runtime, docs, full unit, and GitHub CI gates
