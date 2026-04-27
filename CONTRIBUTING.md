# Contributing

## Setup

```bash
uv python install 3.12
uv sync --all-extras
corepack enable
corepack npm ci
corepack npm run check:ci
```

- The development baseline is Python 3.12+, with CI coverage for 3.12, 3.13, and 3.14.
- Node.js is only used for Husky local hooks. Use the LTS version in `.node-version`
  and `.nvmrc`, then install with `corepack npm ci` so `package-lock.json`
  and `packageManager` stay authoritative.

## Local CI Guards

Husky hooks mirror the required CI checks without making every commit too slow.

```bash
corepack npm ci
corepack npm run check:ci
```

- `pre-commit` is intentionally fast: it checks formatting and lint only for staged Python files.
- `pre-push` runs full lint, strict mypy, and unit tests.
- `corepack npm run check:ci` mirrors the regular validation job: metadata check, lint, typecheck, and coverage-gated tests.
- `corepack npm run check` is the full local release gate: validation, security audit, and package build.
- `corepack npm run security` runs `bandit` and `pip-audit`.
- `uv run pytest --testmon tests/unit/` is useful for local incremental test loops.

## Release Version Bump

Use the release helper so package, runtime, registry metadata, changelog, and lockfile versions stay in sync.

```bash
npm run version:bump -- 1.0.4
npm run metadata:sync
corepack npm run check
```

## Development Workflow

- Keep user-facing messages in English.
- Use typed tool parameters and bounded validation.
- Prefer project-safe path resolution over raw filesystem access.
- Add or update tests for new tools and behavior changes.
- Keep dependency changes synced in both `pyproject.toml` and `uv.lock`.
- Keep `mcp.json` and `server.json` generated from `pyproject.toml` with `npm run metadata:sync`.

## Windows Note

- On Windows, `uv run <python-console-script>` can fail for some packages with `Failed to canonicalize script path`.
- Prefer `uv run python -m pytest`, `uv run python -m mypy`, `uv run python -m bandit`, `uv run python -m pip_audit`, and `uv run python -m safety` for cross-platform local commands.

## Commit Messages

- Conventional Commits are required by the `commit-msg` hook.
- Use prefixes such as `feat:`, `fix:`, `docs:`, `perf:`, `security:`, `deps:`, `refactor:`, `test:`, `ci:`, `build:`, and `chore:`.

## Pull Requests

- Describe the user-facing impact and any API-facing changes.
- Include test evidence or explain why a test was not feasible.
- Keep unrelated refactors out of the same pull request.
- Call out dependency, workflow, or registry metadata changes explicitly.
