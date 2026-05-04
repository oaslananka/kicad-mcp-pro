# Baseline Failures

Baseline command:

```bash
npm run check:ci
```

Result before implementation changes: failed during `npm run workflows:lint`.

Root cause:

- `scripts/check_workflows.py --actionlint` requires the external `actionlint` binary.
- The repository dependencies installed successfully with `npm ci` and `uv sync --all-extras --frozen`, but `actionlint` was not present on the local `PATH`.
- Metadata, format, lint, typecheck, tests with coverage, and security checks completed before this failure.

Resolution:

- Install `actionlint` locally before rerunning the baseline CI gate.
