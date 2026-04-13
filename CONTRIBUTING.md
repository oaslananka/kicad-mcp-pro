# Contributing

## Setup

```bash
uv python install 3.12
uv sync --all-extras
uv run ruff check src/ tests/
uv run python -m mypy src/kicad_mcp/
uv run python -m pytest tests/unit/ tests/integration/ tests/e2e/ -q
```

- The v2 development baseline is Python 3.12+.

## Local CI Guards

Husky hooks mirror the required CI checks without making every commit too slow.

```bash
npm install
npm run check:ci
```

- `pre-commit` runs `ruff` and `mypy`.
- `pre-push` runs the coverage-gated pytest command used by CI.
- `npm run hooks:security` runs `bandit` and `pip-audit` when you want the manual security audit locally.
  The current audit command ignores `CVE-2025-69872` because it is a no-fix transitive `diskcache` advisory pulled in only by the optional `simulation` extra through `InSpice`.

## Release Version Bump

Use the release helper so package, runtime, registry metadata, changelog, and lockfile versions stay in sync.

```bash
npm run version:bump -- 1.0.4
npm run check:ci
```

## Development Workflow

- Keep user-facing messages in English.
- Use typed tool parameters and bounded validation.
- Prefer project-safe path resolution over raw filesystem access.
- Add or update tests for new tools and behavior changes.
- Keep dependency changes synced in both `pyproject.toml` and `uv.lock`.

## Windows Note

- On Windows, `uv run <python-console-script>` can fail for some packages with `Failed to canonicalize script path`.
- Prefer `uv run python -m pytest`, `uv run python -m mypy`, `uv run python -m bandit`, `uv run python -m pip_audit`, and `uv run python -m safety` for cross-platform local commands.

## Commit Messages

- Prefer short, imperative commit subjects.
- Conventional Commit prefixes are welcome when they fit, for example `fix: stabilize LCSC alias output`.

## Pull Requests

- Describe the user-facing impact and any API-facing changes.
- Include test evidence or explain why a test was not feasible.
- Keep unrelated refactors out of the same pull request.
- Call out dependency, workflow, or registry metadata changes explicitly.
