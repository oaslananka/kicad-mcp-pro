# Schematic Template Catalog Service Design

## Context

Issue #434 is incrementally reducing `src/kicad_mcp/tools/schematic.py` into a small FastMCP composition root. The bundled subcircuit template tools still combine registration, filesystem discovery, optional YAML loading, error handling, and Markdown formatting in nested tool functions.

This tranche extracts:

- `sch_list_templates`
- `sch_get_template_info`

`sch_get_circuit_ir` is intentionally excluded because it depends on semantic IR parsing and linting rather than the bundled YAML template catalog.

## Goals

- Make template discovery and rendering directly unit-testable without FastMCP.
- Preserve exact public names, signatures, descriptions, schemas, annotations, sorting, truncation, formatting, error handling, and result strings.
- Preserve lazy PyYAML behavior so server startup does not require eager template parsing.
- Keep the new adapter `register()` function at or below 300 lines.
- Prevent the service and adapter from importing `kicad_mcp.tools.schematic`.

## Non-goals

- No template schema changes.
- No template creation, editing, or instantiation changes.
- No semantic circuit IR extraction in this tranche.
- No new runtime dependencies.

## Architecture

Create `SchematicTemplateCatalogService` in `src/kicad_mcp/schematic/template_catalog.py`. The service receives the template directory and a lazy YAML loader callable. It owns file enumeration, parse error handling, field normalization, and exact Markdown rendering.

Create `src/kicad_mcp/tools/schematic_template_catalog.py` as the thin FastMCP adapter. It preserves the current function signatures and docstrings and delegates to the service.

Keep `src/kicad_mcp/tools/schematic.py` as the composition root. It constructs the service with the existing bundled template path and a lazy loader that imports PyYAML only when called.

## Service Interface

```python
@dataclass(frozen=True)
class SchematicTemplateCatalogService:
    templates_dir: Path
    load_yaml: Callable[[TextIO], Any]

    def list_templates(self) -> str: ...
    def template_info(self, template_name: str) -> str: ...
```

The loader may raise `ModuleNotFoundError` or `ImportError`, which the service translates to the existing PyYAML installation message. Other parse failures retain the existing per-file list fallback or exact template-specific error message.

## Behavior Preservation

### Listing

- Return the existing directory-missing message before importing YAML.
- Sort `*.yaml` paths by filename.
- Use the YAML `name` field or filename stem.
- Collapse description to the first line and truncate it to 80 characters.
- Preserve parameter declaration order.
- Convert each unreadable template into the current parse-failure line and continue.
- Return the existing empty-directory message when no YAML files exist.
- Preserve the final instantiation hint.

### Template details

- Resolve `<template_name>.yaml` in the bundled catalog.
- Preserve sorted available-name output when the requested file is missing.
- Preserve lazy PyYAML failure and parse-error messages.
- Preserve default name/version values and all Markdown sections.
- Preserve parameter, symbol, pin, net, placement-hint, and part-search ordering.
- Preserve omission of empty sections and the exact trailing-newline behavior.

## Security and Path Scope

The public `template_name` behavior remains unchanged. The service joins the provided name with the fixed bundled catalog directory and appends `.yaml`; it does not broaden filesystem access or add mutation behavior.

## Testing

Direct service tests cover missing/empty directories, stable sorting, first-line/truncated descriptions, parameter ordering, per-file parse failures, missing templates, absent PyYAML, parse exceptions, complete section rendering, and omitted sections.

Adapter tests cover exact public names, descriptions, schema requirements, metadata, and delegation. Architecture tests enforce service purity, adapter isolation, and the 300-line limit. Full-server metadata is compared byte-for-byte with `main`, and the committed tool-surface snapshot must remain unchanged.

## Expected Result

The main schematic `register()` function loses approximately 130 lines. Template catalog behavior becomes independently testable while public MCP behavior remains unchanged.
