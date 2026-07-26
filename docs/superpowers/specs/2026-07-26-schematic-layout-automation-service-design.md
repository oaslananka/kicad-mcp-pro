# Schematic Layout Automation Service Design

## Context

Issue #434 requires `src/kicad_mcp/tools/schematic.py` to become a composition root whose domain behavior is independently testable without constructing FastMCP. The remaining `register()` span is 1,110 lines. Four cohesive layout/readability tools account for roughly 440 lines:

- `sch_auto_place_symbols`
- `sch_autoplace_fields`
- `sch_fix_readability`
- `sch_auto_place_functional`

The repository already uses a stable extraction pattern: a FastMCP-independent service under `src/kicad_mcp/schematic/`, a thin adapter under `src/kicad_mcp/tools/`, dependency construction in the original composition root, direct service tests, registration-contract tests, and architecture-boundary checks.

## Goals

- Extract the four layout/readability workflows into a FastMCP-independent service.
- Preserve exact public tool names, descriptions, argument schemas, output schemas, annotations, metadata, messages, write behavior, reload behavior, and error behavior.
- Preserve legacy monkeypatch seams in `tools.schematic` by injecting the existing helper functions and constants from the composition root.
- Reduce the `schematic.register()` span without introducing unrelated refactoring.
- Add direct tests that exercise layout decisions without registering a FastMCP server.

## Architecture

Create `SchematicLayoutAutomationService` in `src/kicad_mcp/schematic/layout_automation.py`. The service owns the four workflows and receives file access, parser/loader functions, geometry helpers, transaction functions, visual-QA helpers, design-intent loading, logging, and layout constants through typed constructor fields. It must not import FastMCP or `tools.schematic`.

Create `src/kicad_mcp/tools/schematic_layout_automation.py` as the thin MCP adapter. It defines the same four nested tool functions with unchanged signatures, decorators, and docstrings, then delegates directly to the service.

`src/kicad_mcp/tools/schematic.py` remains the composition root. It builds the service from the existing private helpers and constants, registers the adapter, and no longer contains the four tool implementations.

## Data and control flow

1. FastMCP validates the public adapter arguments exactly as before.
2. The adapter calls the matching service method with those arguments.
3. The service performs the existing deterministic layout/readability workflow through injected collaborators.
4. The service returns the same text response as the current implementation.
5. Existing transaction, format-preservation, reload, diagnostics, and warning paths remain unchanged because the same composition-root helpers are injected.

## Error handling

- Schematic load/save failures retain the current user-facing messages.
- Load/save failures retain structured warning calls where the current implementation emits them.
- Empty and no-match conditions retain current diagnostic messages.
- Readability loops retain the current minimum-pass behavior, stop conditions, unresolved-code reporting, and conditional reload.
- No new exception swallowing or policy changes are introduced.

## Testing

- Service tests cover successful and failure paths for all four methods with deterministic fakes.
- Registration tests compare tool signatures/descriptions and verify delegation without executing domain logic.
- Architecture tests prove the service has no FastMCP or registry dependency and prove the composition root delegates the four tools.
- Existing integration tests for symbol placement, field placement, readability repair, functional placement, tool-surface snapshots, and metadata remain green.
- Ruff, mypy, architecture checks, generated metadata checks, and focused coverage must pass before push.

## Scope exclusions

- No new placement strategies.
- No changes to functional-zone classification or spacing policy.
- No changes to transaction, approval, checkpoint, or reload semantics.
- No extraction of pin-label, jumper, annotation, reload, routing, or missing-junction tools in this change.
