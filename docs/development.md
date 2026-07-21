# Development

## One-Time Setup

Install Task from <https://taskfile.dev/installation/>.

```bash
task install
task hooks
```

## Local Setup

`pnpm run workflows:lint` and `task workflows:lint` use the exact
`actionlint-py` and `shellcheck-py` versions locked by `uv.lock`. A frozen
`uv sync --all-extras` installs both binaries; no separate global install is
required.

## Daily Workflow

```bash
task format
task lint
task typecheck
task test
task security
task workflows:lint
task workflows:security
task ci
```

## Before Push

The pre-push hook runs:

```bash
task pre-push
```

For full local parity with CI:

```bash
task ci
```

For local workstation security scanners:

```bash
task security:local
```

This command uses the locked actionlint, ShellCheck, and Zizmor binaries from
the project environment. Gitleaks remains a separately installed required
scanner; missing tools fail with explicit installation guidance.

## Optional GitHub Actions Local Run

Install `act` from <https://github.com/nektos/act>, then run:

```bash
act -W .github/workflows/ci.yml --container-architecture linux/amd64
```

## Troubleshooting

- `task: command not found`: install Task from the official installation page.
- Hook setup fails: run `uvx pre-commit install --install-hooks`.
- CI and local results differ: check that environment variables are consistent between local and CI.
