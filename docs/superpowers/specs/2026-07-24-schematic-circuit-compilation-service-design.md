# Schematic Circuit Compilation Service Design

## Context

Issue #434 is incrementally reducing `src/kicad_mcp/tools/schematic.py` into a small FastMCP composition root. `sch_analyze_net_compilation` and `sch_build_circuit` still combine public registration, netlist compilation orchestration, whole-document generation, symbol-library loading, paper-size preservation, transactional writes, warnings, and result rendering inside the registry.

This tranche extracts only those two circuit-compilation tools.

## Goals

- Make net-compilation analysis and whole-schematic generation directly unit-testable without FastMCP.
- Preserve exact public names, signatures, descriptions, schemas, annotations, validation errors, generated schematic text, warning events, transactional behavior, and result notes.
- Preserve existing monkeypatch seams by injecting lazy composition-root wrappers around current helpers.
- Keep the adapter `register()` function at or below 300 lines.
- Keep domain code independent of FastMCP and `kicad_mcp.tools.schematic`.

## Non-goals

- No net-routing, auto-layout, validation, symbol-resolution, or serialization algorithm changes.
- No public input/output changes.
- No changes to transaction safety or approval behavior.
- No new runtime dependencies.

## Architecture

Create `PreparedCircuitInputs` and `SchematicCircuitCompilationService` in `src/kicad_mcp/schematic/circuit_compilation.py`. The service receives explicit callables for input preparation, report rendering, active-file/project resolution, paper declarations, symbol-library loading, primitive block generation, connectivity normalization, validation, transactional writing, reload, and warning emission.

Create `src/kicad_mcp/tools/schematic_circuit_compilation.py` as the thin FastMCP adapter. It preserves both public signatures and docstrings and delegates directly to the service.

Keep `src/kicad_mcp/tools/schematic.py` as the composition root. Lazy wrappers continue resolving current module globals at call time so existing tests and integrations that monkeypatch helper functions after registration keep working.

## Behavior Preservation

- `sch_analyze_net_compilation` invokes the same preparation helper and report renderer with the same routing-mode and explicit-wire calculations.
- `sch_build_circuit` preserves the active paper declaration, including custom User dimensions, and only promotes named paper sizes when auto-layout grows the sheet.
- Unresolved-net warning fields and the complete no-routable-terminal error text remain unchanged.
- Regular and power symbol library definitions remain deduplicated in encounter order.
- Symbol, power, wire, and label blocks retain the same snapping and argument behavior.
- Generated KiCad document structure, connectivity normalization, validation, transaction flags, reload ordering, and result notes remain byte-for-byte compatible.

## Testing

Direct service tests cover analysis delegation, unresolved-net errors and warnings, empty builds, paper preservation/growth, library deduplication, generated document structure, terminal/routed notes, and partial unresolved warnings. Adapter tests pin exact metadata and delegation. Existing integration and tool-surface tests remain the compatibility oracle.

## Expected Result

The main schematic `register()` function loses approximately 290 lines. Circuit compilation becomes independently testable while its public MCP contract and generated schematic behavior remain unchanged.
