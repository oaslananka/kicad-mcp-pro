# ADR-0004: MCP Tool Output-Schema Evolution Policy

**Status:** Accepted
**Date:** 2026-06-27
**Deciders:** @oaslananka

## Context

KiCad MCP Pro exposes ~200 tools, each returning structured `CallToolResult`
payloads (TextContent, ImageContent, or custom JSON schemas). As the tool
surface grows, output schemas inevitably evolve — fields are added, deprecated,
or changed. Without an explicit evolution policy, clients (LLM agents, IDE
extensions, CI pipelines) break silently when a schema changes.

The MCP 2025-11-25 protocol defines `outputSchema` as an optional field on
`Tool`, but the SDK and most clients do not enforce it. The upcoming MCP
A future MCP protocol draft adds tool annotations and stronger schema contracts, including
optional versioned schemas and compatibility hints.

This ADR defines how KiCad MCP Pro evolves its tool output schemas so that:

1. A client written against version X does not silently misinterpret version X+1
   output.
2. The contract test suite detects schema drift (see
   `tests/unit/test_tool_schema_contract.py`).
3. The migration path to 2026-07-28 is clear.

## Decision

### 1. Backward-Compatible Changes (Always Safe)

The following changes are always backward-compatible and require no version
bump, deprecation, or coordination:

- **Adding a new field** to a JSON output dict (clients that ignore unknown
  fields continue to work).
- **Adding an optional field** with a sensible default (clients that read it by
  name get the default when absent).
- **Lengthening a string** value (e.g. a version string from `1.0` → `1.0.0`).
- **Adding a new tool** — existing tools are unaffected.

### 2. Backward-Incompatible Changes (Require Coordination)

The following changes are backward-incompatible and **must** follow the
deprecation process (section 4):

- **Removing a field** from a JSON output dict.
- **Renaming a field** (perceived as removal + addition).
- **Changing a field type** (e.g. `string` → `array`).
- **Narrowing a value domain** (e.g. `0..100` → `0..50`).
- **Changing the error shape** returned by `ToolResult.failure()`.
- **Changing the semantics** of an existing field without changing its name.

### 3. Schema Versioning

Each tool that returns structured JSON output should advertise a
`schemaVersion` field as a top-level key in its output dict (or inside the
TextContent JSON body):

```json
{
  "schemaVersion": "1.2.0",
  "result": "..."
}
```

Schema versions follow [SemVer 2.0](https://semver.org/):

| Component | What it means for tool output schemas |
|-----------|--------------------------------------|
| MAJOR     | Breaking change (removed/renamed/retired field) |
| MINOR     | Backward-compatible addition (new field, new tool) |
| PATCH     | Bug fix, documentation, no semantic change |

Tools that wrap KiCad CLI output (e.g. `export_*`) inherit the KiCad CLI
output format and may break without a MAJOR version warning. For these tools,
the `schemaVersion` tracks the **wrapper layer**, not the format — the wrapper
guarantees its own key structure, not the underlying tool's output format.

For tools that return binary or non-JSON content (images, STEP files, Gerbers),
the schema version applies to the `CallToolResult` envelope structure only,
not the embedded content.

### 4. Deprecation Process

A backward-incompatible change follows a two-release cycle:

1. **Release N** (deprecation):
   - Add the new field alongside the old field.
   - Mark the old field with `"deprecated": true` in the output (or annotate
     in the tool description).
   - Log a warning when the deprecated field is populated.
   - Update `outputSchema` to include both fields.
   - Bump MINOR version.

2. **Release N+1** (removal):
   - Remove the deprecated field.
   - Bump MAJOR version.
   - Document the removal in the changelog.

### 5. Contract Test Enforcement

The contract test suite (`test_tool_schema_contract.py`) pins:

- Every tool has a valid `inputSchema` (JSON Schema draft 2020-12).
- Every tool has a valid `outputSchema` when present.
- Every tool has consistent annotations (`readOnlyHint`, `destructiveHint`,
  `idempotentHint`).
- The `tools/list` response validates against `mcp-tool-discovery.schema.json`.
- Tool names follow `snake_case`.

These tests **fail on drift** — if a tool's schema changes incompatibly, the
test catches it. This is the primary mechanism for detecting unintended schema
evolution.

### 6. Client Compatibility

Clients fall into three categories for schema evolution:

| Client Type | Behavior | Notes |
|-------------|----------|-------|
| **LLM agents** (Claude, GPT, Gemini) | Read JSON with natural-language understanding | Most tolerant — LLMs adapt to new fields automatically |
| **IDE extensions** (VS Code, Cursor, JetBrains) | Display output via structured rendering | Medium tolerance — unknown fields are displayed but not parsed |
| **CI/automation pipelines** | Parse specific fields programmatically | Least tolerant — must pin a schema version |

For CI pipelines that parse tool output, the recommended practice is to check
the `schemaVersion` field before reading known keys:

```python
result = json.loads(response["content"][0]["text"])
if result.get("schemaVersion") == "1.2.0":
    my_field = result["myField"]
else:
    handle_unknown_schema(result)
```

### 7. Migration to future MCP output-schema requirements

A future MCP protocol draft adds `outputSchema` to `Tool` as a required hint. When the
server migrates, each tool must declare an explicit `outputSchema` using the
existing `inputSchema` pattern (JSON Schema draft 2020-12). The migration
path is:

1. Add `outputSchema` to every tool in `list_tools_sync()`.
2. Validate `outputSchema` in the contract test suite.
3. Add `schemaVersion` output field to tools that lack it.
4. Verify the `tools/list` response still validates against
   `mcp-tool-discovery.schema.json`.

## Consequences

- Adding a field is always safe — no deprecation ceremony required.
- Removing or renaming a field requires a two-release deprecation cycle.
- The contract test suite (`test_tool_schema_contract.py`) prevents accidental
  drift.
- CI pipelines should pin on `schemaVersion` to avoid breakage.
- The future output-schema migration will require adding `outputSchema` to all tools,
  but the deprecation process smooths the transition.
