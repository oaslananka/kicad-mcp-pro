# Development

## One-Time Setup

Prepare the repository-scoped toolchain, then install both hooks:

```bash
./scripts/bootstrap-dev.sh
source .dev-env.sh
task hooks
```

The hook launcher reads the committed `UV_VERSION` and refuses a mismatched
global uv. It uses `.dev-tools/uv/<version>/bin/uv`, so other repositories may
use different uv versions without conflict.

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

The pre-push hook runs change-scoped checks only:

```bash
task pre-push
```

It selects Ruff, mypy, matching unit tests, architecture/tool-contract checks,
workflow validation, web route tests, Cargo checks, or compatibility checks from
the files being pushed. It deliberately does not run the repository-wide unit
suite, coverage, package build, docs build, release checks, or security matrix.

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
- Hook setup fails: run `task hooks`.
- CI and local results differ: check that environment variables are consistent between local and CI.
