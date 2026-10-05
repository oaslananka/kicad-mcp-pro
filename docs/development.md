# Development

## One-Time Setup

Prepare the repository-scoped toolchain, then install the repository-pinned
Lefthook hooks:

```bash
./scripts/bootstrap-dev.sh
source .dev-env.sh
task hooks
```

Lefthook is the Git-hook owner for both `pre-commit` and `pre-push`. The FAST
pre-commit catalog remains in `.pre-commit-config.yaml` so its pinned hygiene,
Ruff, and Gitleaks checks keep their existing cross-platform behavior; Lefthook
invokes that catalog rather than letting `pre-commit` install Git hooks itself.
The MEDIUM pre-push path runs `scripts/hook_pre_push.py` directly against the
feature-branch delta from `origin/main`, so rebases and force-pushes validate the
PR patch rather than the old remote branch head.

The uv launcher reads the committed `UV_VERSION` and refuses a mismatched
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

The Lefthook pre-push hook runs change-scoped checks only:

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
- Hook setup fails: run `task hooks`. The installer preserves any global `core.hooksPath` by using a repository-local `.git/hooks` override on normal clones; linked worktrees with a custom hooks path fail closed instead of rewriting shared Git configuration.
- CI and local results differ: check that environment variables are consistent between local and CI.
