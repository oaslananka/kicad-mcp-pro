# Contributing Regression Fixtures

Benchmark and regression fixtures live under `tests/fixtures/benchmark_projects/`. They make bugs reproducible and keep fixed behavior fixed.

## Fixture Policy

- Add a minimal KiCad project for every user-facing regression when possible.
- Keep projects small and remove proprietary data.
- Prefer descriptive names such as `fail_dirty_transfer_wrong_pad_nets`.
- Include only files needed to reproduce the behavior.
- Add a test that fails without the fix and passes with it.

## Privacy Checklist

- No customer board names.
- No internal part numbers unless they are public.
- No secrets, tokens, or private URLs.
- No generated manufacturing package unless the test requires it.

## Test Placement

Use unit tests for pure helpers, integration tests for file-backed tool behavior, and e2e tests for workflow-level regressions.

## Live-preview fixture guidance

Live-preview tests should use the smallest KiCad hierarchy that proves the behavior under test. A useful fixture has:

- one root schematic, usually `demo.kicad_sch`;
- one child sheet, for example `power.kicad_sch`;
- a matching `demo.kicad_pro` project file;
- a minimal board file only when the test also needs PCB context.

The hierarchy fixture `tests/fixtures/benchmark_projects/fail_sismosmart_like_hierarchy/` is a good example of a root sheet plus child sheet layout. Live-preview tests can use this shape to verify that child-sheet edits are detected even when the root sheet itself is unchanged.

## Adding a live-preview fixture

1. Start from a minimal public KiCad project.
2. Keep the root sheet and one child sheet unless the regression specifically needs more hierarchy.
3. Use synthetic references and net names such as `R1`, `U1`, `GND`, `READY`, or `CHILD_LIVE`.
4. Avoid vendor-specific or customer-specific identifiers unless they are public examples.
5. Add a test that documents which file should appear in `changed_files`.
6. Prefer rendered evidence or manifest assertions over brittle timestamp-only checks.

## Review checklist

- The fixture contains no private project names, hostnames, paths, or component sourcing credentials.
- The fixture is small enough to inspect in a pull request.
- The test explains whether it is checking root-sheet watch behavior, child-sheet discovery, debounce behavior, or fallback rendering.
- The fixture does not require a graphical KiCad session unless the test is explicitly marked as GUI-only.
