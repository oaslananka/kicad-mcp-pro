# Schematic Layout Inspection Service Design

## Context

Issue #434 is incrementally extracting schematic domain behavior from the FastMCP registration monolith without changing the public MCP contract. After the hierarchy-authoring tranche, `src/kicad_mcp/tools/schematic.py::register()` still contains 24 nested tools and spans 2,259 lines.

`sch_get_bounding_boxes` and `sch_find_free_placement` form a small, read-only layout-inspection boundary. Both parse the active schematic and use the same symbol geometry and occupancy helpers. They do not mutate files, reload KiCad, or depend on GUI state.

## Scope

Extract exactly these public tools:

- `sch_get_bounding_boxes`
- `sch_find_free_placement`

The tranche must preserve tool names, signatures, descriptions, defaults, schemas, headless metadata, count clamping, formatting, diagnostics, coordinate ordering, keepout behavior, and result strings.

The tranche does not move symbol placement, automatic layout, rendering, readability fixes, sheet resizing, or functional placement.

## Architecture

Create a FastMCP-independent `SchematicLayoutInspectionService` in `kicad_mcp.schematic.layout_inspection`. The service receives existing behavior through constructor-injected callables:

- active schematic path resolution
- schematic parsing
- empty-result diagnostics
- symbol bounding-box estimation
- occupied-cell estimation
- keepout-cell expansion
- next-free-cell search

Create `kicad_mcp.tools.schematic_layout_inspection` as a thin FastMCP adapter. It owns only the two public function signatures, exact docstrings, headless metadata, and delegation.

Keep `kicad_mcp.tools.schematic` as the composition root. It constructs the service from the existing private helpers, registers the adapter once, and removes the two legacy nested functions.

## Data Flow

### Bounding boxes

1. Resolve the active schematic path.
2. Parse the schematic and concatenate normal and power symbols in the existing order.
3. Return the existing diagnostic-wrapped empty message when no symbols exist.
4. Estimate each symbol bounding box with the injected existing helper.
5. Render the existing fixed-width table and occupied-region summary exactly.

### Free placement

1. Clamp `count` to the existing inclusive range of 1 through 64.
2. Resolve and parse the active schematic.
3. Build occupied cells from normal and power symbols.
4. Expand optional rectangular keepouts into occupied cells.
5. Request coordinates sequentially from the injected next-free-cell helper, preserving its mutation of the occupied set.
6. Round coordinates to four decimals and render the existing summary and invocation hint exactly.

## Error Handling

No new exception translation is introduced. Parser, geometry, invalid cell-size, and malformed keepout behavior remains owned by the injected existing helpers. Empty schematics retain the existing diagnostic behavior for bounding boxes and the existing coordinate-generation behavior for free placement.

## Testing

Direct service tests cover:

- empty schematic diagnostics
- exact bounding-box table formatting and occupied summary
- normal/power symbol ordering
- count clamping to 1 and 64
- existing-symbol avoidance
- keepout expansion and forwarding
- sequential coordinate allocation and rounding
- exact result strings

Adapter tests cover exact names, descriptions, defaults, schemas, headless metadata, Pydantic validation, and argument delegation.

Architecture tests require the service to remain pure, forbid the adapter from importing the schematic monolith, and enforce a 300-line adapter `register()` limit.

Full-server metadata comparison and the committed tool-surface snapshot must remain unchanged. Focused coverage must meet the repository threshold, and all repository quality, security, documentation, package, performance, and unit gates must pass.

## Security and Compatibility

This tranche adds no runtime dependency and performs no new file or network access. OSV, Sonar secret analysis, Semgrep Cloud, CodeQL, dependency review, Socket, and the existing workflow-security gates remain part of verification. The pull request references #434 without closing it because further extraction tranches remain.
