# Contributing to KiCad MCP Pro

Thank you for improving KiCad MCP Pro. Keep changes focused, include tests for
behavioral changes, and use Conventional Commit messages.

## Community standards

By participating, contributors agree to follow [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

Contribution mechanics are documented in [`docs/development/commit-conventions.md`](docs/development/commit-conventions.md), [`docs/development/testing-policy.md`](docs/development/testing-policy.md), and [`docs/development/release-process.md`](docs/development/release-process.md). Security-sensitive findings must be reported privately through [`SECURITY.md`](SECURITY.md), not through public issues or pull requests.

## Developer Certificate of Origin

Contributions use the Developer Certificate of Origin (DCO) 1.1. By contributing, you certify that you have the right to submit the work under this project's license and that the contribution can be included in the project.

Add a `Signed-off-by` line to each commit when practical:

```text
Signed-off-by: Your Name <you@example.com>
```

You can create this automatically with:

```bash
git commit -s
```

If a contributor cannot use commit sign-off, they must state in the pull request that they have the right to submit the contribution under the project license. Maintainers may ask for the commits to be amended before merge.

## Coding standards

Follow [`docs/development/coding-standards.md`](docs/development/coding-standards.md). In brief: keep changes focused, typed, testable, and honest about heuristic behavior; do not bypass the KiCad adapter seam; avoid direct use of untrusted paths or shell interpolation; and update generated docs when tool contracts change.

## Development Setup

Requirements:

- Node.js 24 and pnpm 11 through Corepack
- Python 3.13 and uv
- Rust stable for the optional Tauri desktop application

Install the development dependencies:

```bash
corepack enable
corepack pnpm install --frozen-lockfile
uv sync --all-extras --frozen
```

Copy `.env.example` to `.env` only when local overrides are needed. Never commit
credentials or local environment files.

## Quality Gates

Run the focused checks while developing:

```bash
corepack pnpm run format:check
corepack pnpm run lint
corepack pnpm run typecheck
corepack pnpm run test:unit
```

Before opening a pull request, run the full local CI equivalent:

```bash
task ci
```

See [`docs/testing.md`](docs/testing.md) and [`docs/development/testing-policy.md`](docs/development/testing-policy.md) for the test layers and test expectations, and [`docs/repository-operations.md`](docs/repository-operations.md) for release and maintenance policies.

## Add a tool in an afternoon

The server is deliberately structured so that adding a capability is a one-module,
one-registry-entry change. Start with [`docs/development/architecture.md`](docs/development/architecture.md) — the
five-layer map and the **"How to add a new tool"** section are the authoritative
walkthrough. The short loop:

1. **Implement** the tool inside the matching `src/kicad_mcp/tools/*.py` module's
   `register(mcp)` (decorated with `@mcp.tool()`). Keep KiCad-touching calls behind
   the adapter seam and pure logic in `utils/` so it is unit-testable.
2. **Register** the tool name under the right category in `TOOL_CATEGORIES`
   (`tools/router.py`) and confirm the category is in the profiles that should
   expose it. Mark experimental tools in `EXPERIMENTAL_TOOL_NAMES`.
3. **Annotate** read-only / destructive / headless / requires-KiCad metadata via
   `tools/metadata.py`.
4. **Regenerate + verify**: `pnpm run docs:tools` and `pnpm run metadata:check`.
   The registry-consistency and tool-surface-snapshot tests flag any drift.
5. **Test** the pure logic with a unit test; gate KiCad-driving paths behind the
   KiCad-enabled CI job.

Then `task verify` must be green. Honesty rule: if a capability is heuristic,
approximate, or partial, say so in the tool name, docstring, and verdict — never
claim a precision the code does not deliver.

## Issue and pull request hygiene

Use the GitHub issue templates for bugs, feature requests, and documentation reports. Keep pull requests focused, include test evidence, update generated docs and metadata when public contracts change, and avoid attaching private board files, credentials, generated manufacturing files, or customer-specific logs.

## Pull Requests

1. Open a focused branch from `main`.
2. Add or update tests and documentation with the implementation.
3. Use a Conventional Commit title such as `fix: handle missing KiCad CLI`.
4. Confirm all required GitHub Actions checks pass.
5. Merge it yourself — with GitHub's native "Merge when ready" / `gh pr merge --auto`, or a direct merge once checks pass.

Mergify (`.mergify.yml`) only auto-merges grouped Dependabot minor/patch
updates; its `queue_conditions` require `author = dependabot[bot]`. On every
other pull request — including yours — Mergify still posts a "Merge Queue
Status: Waiting for queue conditions" comment. That comment is expected
noise: it previews what the dependabot-only queue rule would need, but the
PR can never actually enter that queue, so the comment never resolves and
does not block or drive your merge.

Report vulnerabilities privately through the process in
[`SECURITY.md`](SECURITY.md).
