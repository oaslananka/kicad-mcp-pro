# Development

## One-Time Setup

Install Task from <https://taskfile.dev/installation/>.

```bash
task install
task hooks
```

## Daily Workflow

```bash
task format
task lint
task typecheck
task test
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

## Optional GitHub Actions Local Run

Install `act` from <https://github.com/nektos/act>, then run:

```bash
act -W .github/workflows/ci.yml --container-architecture linux/amd64
```

## Troubleshooting

- `task: command not found`: install Task from the official installation page.
- Hook setup fails: run `uvx pre-commit install --install-hooks`.
- CI and local results differ: run `task doppler:check` and verify the same Doppler project/config are used.
