# Testing Guide - kicad-mcp-pro

## Overview

kicad-mcp-pro uses **pytest** with the **uv** toolchain. Tests are organised into
three layers:

| Layer       | Path                 | Description                        |
| ----------- | -------------------- | ---------------------------------- |
| Unit        | `tests/unit/`        | Pure Python, no KiCad dependency   |
| Integration | `tests/integration/` | Requires kicad-cli in PATH         |
| Smoke       | `tests/smoke/`       | End-to-end MCP protocol over stdio |

## Running Tests Locally

```bash
# Install all extras (includes test deps)
uv sync --all-extras --frozen

# Unit tests only (fast, no KiCad needed)
uv run pytest tests/unit/ -v

# Full suite (requires KiCad installed)
uv run pytest -v

# With coverage
uv run pytest --cov=kicad_mcp_pro --cov-report=term-missing
```

If `uv run` exits before Python starts with a required-version mismatch, compare
`uv --version` with `uv.toml`. Source checkouts pin the supported uv version so
local and CI dependency resolution match. Run `kicad-mcp-pro doctor --json` for
an explicit `uv_version` diagnostic, then switch to the repo-compatible version,
for example `uv self update 0.11.31` when `uv.toml` requires `0.11.31`.

## CI Matrix

CI runs in the canonical `oaslananka/kicad-mcp-pro` GitHub repository on
GitHub-hosted runners. Python **3.13** is the required PR/push lane for the MCP
server, and package publishing uses the release workflows documented in
`docs/publishing.md`.

## Fixtures

KiCad project fixtures live in `tests/fixtures/`. See
`docs/development/contributing-fixtures.md` for how to add new ones.
Convention: one directory per test scenario, named `<scenario>/`.

## Mutation Testing

Mutation tests run weekly via `.github/workflows/mutation.yml` using
**mutmut**. Check the Actions tab for the latest mutation score. Target
is **>= 70% survived mutations caught**.

## Mocking Strategy

- `conftest.py` root: common fixtures (temp dirs, fake KiCad stubs)
- KiCad CLI is mocked via `unittest.mock.patch` in unit tests
- Integration tests spin up a real `kicad-cli` process (Linux CI only)

## Adding a Test

1. Pick the correct layer (unit if no KiCad needed).
2. Create `tests/<layer>/test_<module>.py`.
3. Follow Arrange-Act-Assert pattern.
4. Run `uv run pytest tests/<layer>/test_<module>.py -v` locally.
5. Ensure `uv run ruff check tests/` passes.
