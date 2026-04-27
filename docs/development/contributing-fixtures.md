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
