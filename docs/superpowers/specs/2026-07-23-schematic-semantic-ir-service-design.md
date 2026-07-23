# Schematic Semantic IR Service Design

## Context

Issue #434 is incrementally reducing `src/kicad_mcp/tools/schematic.py` into a small FastMCP composition root. `sch_get_circuit_ir` still combines registration, active-file lookup, lazy semantic-IR imports, parsing, diagnostic fallback, Markdown rendering, lint execution, and result caching inside the monolithic registry.

This tranche extracts only `sch_get_circuit_ir`.

## Goals

- Make semantic-IR orchestration and summary rendering directly unit-testable without FastMCP.
- Preserve the exact public tool name, signature, description, schema, annotations, cache behavior, lazy import timing, log event, diagnostic fallback, sorting, truncation, formatting, and result text.
- Keep the new adapter `register()` function at or below 300 lines.
- Keep the service independent of FastMCP and `kicad_mcp.tools.schematic`.
- Avoid introducing an import cycle through `kicad_mcp.ir.from_kicad`, which currently imports schematic compatibility helpers.

## Non-goals

- No semantic IR model, parser, lint-rule, or serialization changes.
- No JSON output conversion.
- No new schematic features or public fields.
- No changes to template catalog or template instantiation tools.
- No new runtime dependencies.

## Architecture

Create `SchematicSemanticIRService` in `src/kicad_mcp/schematic/semantic_ir.py`. The service receives callables for active-file resolution, semantic-IR parsing, linting, diagnostic wrapping, and parse-failure logging. It owns parse-error translation and exact Markdown summary rendering.

The service uses local structural protocols rather than importing `kicad_mcp.ir` at module import time. This preserves service purity and prevents the existing `ir.from_kicad -> tools.schematic` dependency from becoming a circular import.

Create `src/kicad_mcp/tools/schematic_semantic_ir.py` as the thin FastMCP adapter. It preserves the current no-argument signature, docstring, `headless_compatible` metadata, and ten-second TTL cache and delegates to the service.

Keep `src/kicad_mcp/tools/schematic.py` as the composition root. Add lazy dependency wrappers that import `lint_circuit` and `parse_schematic_to_ir` only when the tool is called, construct the service, register the adapter, and remove the nested legacy function.

## Service Interface

```python
@dataclass(frozen=True)
class SchematicSemanticIRService:
    active_schematic_file: Callable[[], Path]
    parse_circuit: Callable[[Path], CircuitLike]
    lint_circuit: Callable[[CircuitLike], Iterable[FindingLike]]
    with_diagnostics: Callable[[str, Path], str]
    warn_parse_failure: Callable[[Exception], None]

    def get_summary(self) -> str: ...
```

`CircuitLike`, component/net/rail/interface protocols, and lint-finding protocols expose only the attributes and methods required by the existing renderer.

## Behavior Preservation

- Resolve the active schematic before parsing.
- Load pin metadata during semantic-IR parsing exactly as today.
- On any parse exception, emit the existing `sch_get_circuit_ir parse failed` log event and return `_with_schematic_diagnostics("Could not parse IR: ...", sch_file)`.
- Preserve title, source path, UUID fallback, summary counts, and blank-line layout.
- Sort component, net, rail, and interface names exactly as today.
- Preserve DNP/NoBOM flags, pin counts, power/voltage tags, rail-net truncation to five names, source formatting, interface reference truncation to three names, and role declaration order.
- Preserve lint ordering from the injected lint engine and exact severity/subject/detail formatting.
- Preserve omission of empty sections and exact trailing-newline behavior.
- Preserve the adapter's ten-second TTL cache.

## Testing

Direct service tests cover parse failure/logging/diagnostics, an empty circuit, complete component/net/rail/interface rendering, sorting, truncation, flags, voltage tags, and lint formatting.

Adapter tests cover the exact public name, description, empty schema, headless metadata, TTL cache behavior, and delegation. Architecture tests enforce service purity, adapter isolation, and the 300-line registration limit. Focused integration, metadata equality, and tool-surface snapshot tests prove the public contract remains unchanged.

## Expected Result

The main schematic `register()` function loses approximately 90 lines. Semantic-IR tool behavior becomes independently testable while lazy imports and the observable MCP contract remain unchanged.
