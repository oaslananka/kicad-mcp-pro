# Schematic Template Instantiation Service Design

## Context

Issue #434 is incrementally reducing `src/kicad_mcp/tools/schematic.py` into a small FastMCP composition root. The template catalog tranche extracted read-only discovery and detail rendering, but `sch_instantiate_template` still combines registration, bundled-path resolution, optional YAML loading, parameter resolution, and Markdown action-plan rendering in the monolithic registry.

This tranche extracts only `sch_instantiate_template`.

## Goals

- Make template action-plan generation directly unit-testable without FastMCP.
- Preserve the exact public tool name, signature, description, schema, annotations, argument ordering, lazy PyYAML behavior, error messages, and Markdown output.
- Keep the new adapter `register()` function at or below 300 lines.
- Keep the service independent of FastMCP and `kicad_mcp.tools.schematic`.
- Reduce the main schematic `register()` span through one bounded, reviewable change.

## Non-goals

- No template schema changes.
- No direct schematic mutation or automatic execution of the generated plan.
- No changes to `sch_list_templates` or `sch_get_template_info`.
- No semantic circuit IR extraction.
- No new runtime dependencies.

## Architecture

Create `SchematicTemplateInstantiationService` in `src/kicad_mcp/schematic/template_instantiation.py`. The service receives the fixed bundled template directory and a lazy YAML loader factory. It owns file lookup, parse handling, parameter default/override resolution, reference-prefix formatting, and exact Markdown rendering.

Create `src/kicad_mcp/tools/schematic_template_instantiation.py` as the thin FastMCP adapter. It preserves the existing function signature and docstring and delegates to the service.

Keep `src/kicad_mcp/tools/schematic.py` as the composition root. It constructs the service with the existing bundled template path and `_template_yaml_loader_factory`, registers the adapter, and removes the nested legacy implementation.

## Service Interface

```python
@dataclass(frozen=True)
class SchematicTemplateInstantiationService:
    templates_dir: Path
    yaml_loader_factory: Callable[[], YamlLoader]

    def instantiate(
        self,
        template_name: str,
        prefix: str = "",
        params: dict[str, object] | None = None,
    ) -> str: ...
```

## Behavior Preservation

- Resolve `<template_name>.yaml` under the fixed bundled catalog directory.
- Preserve sorted available-template names when the requested file is missing.
- Import PyYAML lazily and retain the exact installation message.
- Retain the exact template-specific parse-error message.
- Resolve declared parameter defaults, then apply caller overrides.
- Preserve declaration order for parameters, symbols, nets, search hints, and placement hints.
- Preserve current symbol numbering and prefix trimming.
- Preserve placeholder substitution in part-search queries.
- Preserve the existing empty-search fallback and exact Markdown layout.

## Security and Path Scope

The public path behavior remains unchanged. The service joins the caller-provided name with the fixed catalog directory and appends `.yaml`; it does not broaden filesystem access or introduce mutation behavior.

## Testing

Direct service tests cover missing templates, absent PyYAML, parse failures, defaults and overrides, trimmed prefixes, symbol numbering, nets, search substitution, empty search fallback, placement hints, and exact output text.

Adapter tests cover the exact public name, description, schema, required fields, headless metadata, argument forwarding, and delegation. Architecture tests enforce service purity, adapter isolation, and the 300-line registration limit. Focused integration and tool-surface snapshot tests prove that the public contract remains unchanged.

## Expected Result

The main schematic `register()` function loses approximately 100 lines. Template instantiation behavior becomes independently testable while the observable MCP contract remains unchanged.
