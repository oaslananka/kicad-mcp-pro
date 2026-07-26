# Schematic Connectivity Authoring Service Design

## Context

`src/kicad_mcp/tools/schematic.py::register()` is 699 lines after the layout-automation extraction. Three remaining nested tools form one coherent capability boundary:

- `sch_add_pin_labels`
- `sch_route_wire_between_pins`
- `sch_add_missing_junctions`

They all author or repair schematic connectivity and currently mix FastMCP registration with file parsing, pin resolution, geometry, transaction orchestration, and reload behavior.

## Goal

Move connectivity-authoring orchestration behind a FastMCP-independent service while preserving the exact public MCP contract and legacy helper seams.

## Non-goals

- No routing algorithm change.
- No schema, description, annotation, metadata, error-message, transaction, reload, or target-resolution change.
- No extraction of `sch_add_jumper`, `sch_annotate`, or `sch_reload`; those remain a separate bounded change.
- No broad movement of low-level schematic geometry helpers.

## Architecture

Create `SchematicConnectivityAuthoringService` in `src/kicad_mcp/schematic/connectivity_authoring.py`.

The service receives all monolith-owned helpers through constructor injection. It exposes:

```python
add_pin_labels(
    connections: list[dict[str, Any]],
    stub_mm: float = 5.08,
    global_labels: bool = True,
    sheet: str | None = None,
    sheet_file: str | None = None,
) -> str

route_wire_between_pins(
    ref1: str,
    pin1: str,
    ref2: str,
    pin2: str,
    snap_to_grid: bool = True,
) -> str

add_missing_junctions() -> str
```

Create `src/kicad_mcp/tools/schematic_connectivity_authoring.py` as a thin FastMCP adapter. The adapter owns decorators, docstrings, public signatures, and `headless_compatible` metadata only.

`src/kicad_mcp/tools/schematic.py` remains the composition root. It constructs the service with existing helpers, delegates registration to the adapter, and keeps `run_auto_add_missing_junctions` available for `tools.fixers` and existing monkeypatch tests.

## Dependency boundary

The domain service must not import:

- FastMCP or `mcp`
- `kicad_mcp.tools.schematic`
- KiCad GUI/IPC modules directly

The adapter must not import the schematic monolith.

Target, configuration, loaded-symbol, bounding-box, and block-builder surfaces are represented by small Protocols or callable aliases in the service module.

## Contract preservation

Tests must compare all three tools against the current full-server contract:

- name
- description
- input schema
- output schema
- inferred annotations
- tool metadata

The committed tool-surface snapshot and generated tools documentation must remain unchanged.

## Error and transaction behavior

- Missing references and pins keep the same returned strings.
- Pin-label partial-success reporting remains unchanged.
- Pin-label target selection still accepts `sheet` or `sheet_file` and reports target detail.
- Writes continue through the existing transactional functions.
- Reload remains best-effort and retains existing response ordering.
- Missing-junction repair continues to call the module-level fixer seam before reload.

## Verification

- Red-green service and adapter tests.
- Existing pin-label, routing, and junction integration tests.
- Exact full-server contract comparison.
- Architecture-boundary and register-span checks.
- Ruff, mypy, Pyright, tool-contract, metadata, parity, strict docs, and representative latency checks.
- Full repository CI after PR creation.
