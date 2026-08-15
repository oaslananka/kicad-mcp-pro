# Issue #680 Schematic Runtime Discovery Design

## Problem

File-backed schematic authoring tools are incorrectly classified as requiring live KiCad IPC. When the schematic editor is closed, runtime filtering removes these tools from `tools/list` even though their services read and write `.kicad_sch` files directly and only attempt an IPC reload opportunistically after a successful file write.

This creates two inconsistent truths: server capability reporting can describe a tool as available while MCP `tools/list` hides it. The safe headless workflow therefore loses the authoring tools it needs.

## Goals

- Keep file-backed schematic authoring and variant tools discoverable when no live schematic window exists.
- Preserve IPC gating for operations that genuinely require a live KiCad schematic context.
- Make runtime classification consistent with actual service dependencies rather than access tier alone.
- Add regression coverage for both discovery and capability metadata.
- Fix issue #680 without broad unrelated refactoring.

## Chosen Design

Treat the `schematic` router category as file-backed by default. `_runtime_for_tool()` will return `RuntimeRequirement.NONE` for schematic-category tools unless the tool is an explicit live-editor exception.

At present the only verified schematic-category operation whose primary behavior requires IPC is `sch_reload`. It will remain `RuntimeRequirement.KICAD_IPC` and its wrapper will be marked with `@requires_kicad_running` so discovery metadata and capability metadata agree.

File-backed services may still call the existing reload helper after writing. That helper is opportunistic: when KiCad or a schematic document is unavailable it returns a manual-reload note rather than failing the file edit. Such tools therefore do not require IPC for correctness and must not be filtered from `tools/list`.

## Capability Invariants

- `sch_reload.runtime == KICAD_IPC`.
- Other schematic-category tools default to `RuntimeRequirement.NONE` unless a future tool is explicitly proven to require live IPC.
- A file-backed write tool may have `writes_files=True` while `writes_kicad_gui_state=False`.
- Runtime filtering must keep file-backed schematic tools visible when `live_schematic_context=False`.
- Runtime filtering must continue hiding `sch_reload` when no live schematic context exists.

## Regression Coverage

Capability tests will assert representative file-backed tools resolve to `RuntimeRequirement.NONE`, including hierarchy, connectivity, destructive-edit, rendering/preview, and variant examples. `sch_reload` will assert `RuntimeRequirement.KICAD_IPC`.

Server runtime-filter tests will construct a reachable KiCad state with `live_schematic_context=False` and verify representative tools such as `sch_create_sheet`, `sch_add_pin_labels`, `sch_live_preview`, `sch_delete_no_connect`, and `variant_create` remain allowed while `sch_reload` is rejected.

Registration metadata tests will assert `sch_reload` is marked `requires_kicad_running=True`.

## Validation

Run targeted capability/runtime-filter/registration tests first, then the relevant schematic registration suites. Run Ruff, mypy/pyright where touched modules are covered, generated adapter/tool metadata checks, `git diff --check`, and the repository's progressive-disclosure/tool-surface checks if classification changes alter generated evidence.

## Non-Goals

- Do not change PCB runtime classification.
- Do not redesign the entire capability registry.
- Do not add a 40+ tool name allowlist.
- Do not change schematic write semantics or IPC reload behavior.
- Do not merge the resulting PR automatically.

## Release Intent

Land as a focused `fix(...)` before the 3.32.1 release PR. The PR body should include `Fixes #680`. Feature PRs #683, #684, and #686 remain outside this hotfix line.