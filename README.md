<div align="center">

<h1>KiCad MCP Pro</h1>

<p>
  <strong>Drive KiCad schematic, PCB, DRC/ERC, DFM, and manufacturing review from any MCP-capable AI agent.</strong>
</p>

<p>
  <a href="https://oaslananka.github.io/kicad-mcp-pro/">Documentation</a> ·
  <a href="docs/installation.md">Installation</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="docs/tools-reference.generated.md">Tool Reference</a> ·
  <a href="https://oaslananka.github.io/kicad-mcp-pro/agents/">AI Agent Setup</a> ·
  <a href="docs/llms.txt">AI discovery</a>
</p>

<p>
  <a href="https://pypi.org/project/kicad-mcp-pro/"><img src="https://img.shields.io/pypi/v/kicad-mcp-pro?label=pypi" alt="PyPI Version" /></a>
  <a href="https://www.npmjs.com/package/kicad-mcp-pro"><img src="https://img.shields.io/npm/v/kicad-mcp-pro?label=npm" alt="npm Version" /></a>
  <a href="https://pypi.org/project/kicad-mcp-pro/"><img src="https://img.shields.io/pypi/pyversions/kicad-mcp-pro?label=python" alt="Python Version" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="MIT License" /></a>
  <a href="https://doi.org/10.5281/zenodo.21283791"><img src="https://zenodo.org/badge/1255527274.svg" alt="DOI" /></a>
</p>

<p>
  <a href="https://github.com/oaslananka/kicad-mcp-pro/actions/workflows/ci.yml"><img src="https://github.com/oaslananka/kicad-mcp-pro/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="https://github.com/oaslananka/kicad-mcp-pro/actions/workflows/gui-ci.yml"><img src="https://github.com/oaslananka/kicad-mcp-pro/actions/workflows/gui-ci.yml/badge.svg?branch=main" alt="GUI CI" /></a>
  <a href="https://github.com/oaslananka/kicad-mcp-pro/actions/workflows/codeql.yml"><img src="https://github.com/oaslananka/kicad-mcp-pro/actions/workflows/codeql.yml/badge.svg?branch=main" alt="CodeQL" /></a>
  <a href="https://securityscorecards.dev/viewer/?uri=github.com/oaslananka/kicad-mcp-pro"><img src="https://api.scorecard.dev/projects/github.com/oaslananka/kicad-mcp-pro/badge" alt="OpenSSF Scorecard" /></a>
  <a href="https://www.bestpractices.dev/projects/13377"><img src="https://www.bestpractices.dev/projects/13377/badge" alt="OpenSSF Best Practices: Silver" /></a>
</p>

<p>
  <a href="https://pepy.tech/project/kicad-mcp-pro"><img src="https://static.pepy.tech/badge/kicad-mcp-pro" alt="PyPI total downloads" /></a>
  <a href="https://www.npmjs.com/package/kicad-mcp-pro"><img src="https://img.shields.io/npm/dt/kicad-mcp-pro?label=npm%20downloads" alt="npm total downloads" /></a>
</p>

<!-- parity-coverage-badge:start -->
[![KiCad programmatic parity](https://img.shields.io/badge/KiCad_programmatic_parity-76.3%25-green)](docs/compatibility/capability-parity.generated.md)
<!-- parity-coverage-badge:end -->

<p>
  <a href="https://www.buymeacoffee.com/oaslananka"><img src="https://img.shields.io/badge/sponsor-Buy%20me%20a%20coffee-ffdd00?logo=buymeacoffee&logoColor=black" alt="Buy me a coffee" /></a>
</p>

</div>

<!-- mcp-name: io.github.oaslananka/kicad-mcp-pro -->

KiCad MCP Pro is a Model Context Protocol server for KiCad EDA workflows. It exposes tools, resources, and prompts for schematic, PCB, validation, DFM, and manufacturing export automation.

The server now starts with the bounded `default` profile: 24 read-only review tools instead of the complete 377-tool expert catalog. Use `build` with write mode for controlled edits, `release` with manufacturing mode for human-gated handoff, or `expert`/`full` only for advanced trusted clients. See [`docs/agents/progressive-disclosure.md`](docs/agents/progressive-disclosure.md).

Telemetry and error reporting are disabled by default. Opt-in OpenTelemetry
configuration is documented in
[`docs/configuration.md`](docs/configuration.md#opentelemetry), and privacy rules
are documented in [`docs/privacy.md`](docs/privacy.md).

## Scope and honesty

KiCad MCP Pro is a **professional first-pass design and review assistant**, not an
automated sign-off authority. ERC/DRC and the export pipeline drive KiCad's own
engines. The signal-integrity, power-integrity, EMC, and thermal tools are
**first-order, closed-form estimates** (typically ~5–10% accuracy) — fast first-pass
review, **not** a substitute for a 2D/3D field solver, EM/FEA simulation, or formal
sign-off. Live component sourcing uses the JLCPCB public catalog by default; Nexar,
DigiKey, and Mouser are available only when their API credentials are configured. What
fraction of KiCad's programmatic surface the server drives is tracked openly in the
[capability-parity matrix](docs/compatibility/capability-parity.generated.md).

## Project identity

| Field | Value |
| --- | --- |
| Canonical repository | [`oaslananka/kicad-mcp-pro`](https://github.com/oaslananka/kicad-mcp-pro) |
| PyPI package | [`kicad-mcp-pro`](https://pypi.org/project/kicad-mcp-pro/) |
| npm wrapper | [`kicad-mcp-pro`](https://www.npmjs.com/package/kicad-mcp-pro) |
| MCP Registry name | `io.github.oaslananka/kicad-mcp-pro` |
| Version | `3.27.0` | <!-- x-release-please-version -->
| OSS maturity report | [`docs/repo-maturity-report.md`](docs/repo-maturity-report.md) |
| OpenSSF evidence | [`docs/openssf-evidence.md`](docs/openssf-evidence.md) |

## Quick Start

### Desktop App

Download the latest installer from the
[GitHub releases page](https://github.com/oaslananka/kicad-mcp-pro/releases).
The Tauri desktop app starts the Python dashboard server automatically and opens
the GUI at `http://127.0.0.1:3334/ui`.

### CLI

```bash
uvx kicad-mcp-pro init
uvx kicad-mcp-pro tray
uvx kicad-mcp-pro dashboard --open
uvx kicad-mcp-pro --transport streamable-http --port 3334
```

### Web Dashboard

```bash
uvx kicad-mcp-pro dashboard --host 127.0.0.1 --port 3334 --open
# http://127.0.0.1:3334/ui
```

## Documentation

The documentation is organized from setup to operation:

1. [Installation](docs/installation.md)
2. [Client configuration](docs/client-configuration.md)
3. [Runtime configuration](docs/configuration.md)
4. [Tool reference](docs/tools-reference.md)
5. [Workflows](docs/workflows/first-pcb.md)
6. [Release process](docs/release-process.md)
7. [Security and privacy](docs/security/threat-model.md)
8. [KiCad capability parity](docs/compatibility/capability-parity.generated.md) — how much of KiCad's programmatic surface this server drives
9. [Error code catalog](docs/errors.md) — stable error codes, retry classes, and recovery
10. [Work-order audit](docs/status/work-order-audit-2026-06-17.md) — current status of the hardening work order

The `kicad_capability_parity()` tool reports, per workflow domain, what fraction of
KiCad's programmatically reachable surface this server can drive (currently **76.3%**),
keeping genuine `gap`s distinct from `gui-only-no-api` items that KiCad exposes no
headless API for.

The published documentation site is available at
[https://oaslananka.github.io/kicad-mcp-pro/](https://oaslananka.github.io/kicad-mcp-pro/).

## Transports

KiCad MCP Pro supports `stdio` and Streamable HTTP. Streamable HTTP is served at
`/mcp` by default and can be moved with `KICAD_MCP_MOUNT_PATH`.

```bash
uvx kicad-mcp-pro --transport streamable-http --host 127.0.0.1 --port 3334
```

Streamable HTTP clients must send:

- `Accept: application/json, text/event-stream`
- `Content-Type: application/json`
- `MCP-Protocol-Version: 2025-11-25` after initialization
- `MCP-Session-Id` on follow-up requests when `KICAD_MCP_STATEFUL_HTTP=1`

By default Streamable HTTP is stateless, so ChatGPT-style connectors can
initialize and call `tools/list` without a session-header injection proxy. Set
`KICAD_MCP_STATEFUL_HTTP=1` to require session IDs after `initialize`.

The deprecated HTTP+SSE fallback routes are disabled by default. Set
`KICAD_MCP_LEGACY_SSE=1` only for older clients that cannot use Streamable HTTP.

## Install

Published packages:

```bash
uvx kicad-mcp-pro --help
npx kicad-mcp-pro --help
```

Fresh source checkout on supported Linux hosts:

```bash
./scripts/bootstrap-dev.sh
source .dev-env.sh
pnpm run dev:doctor -- --ci
```

The repository bootstrap installs checksum-pinned Python, uv/uvx, Node.js,
pnpm, Task, and Rust tooling into ignored checkout-local roots and performs
frozen dependency installation. It does not modify global tool directories.
See the [reproducible bootstrap guide](docs/development/reproducible-bootstrap.md)
for `--core-only`, `--check`, cleanup, upgrade, and KiCad capability modes.

## Package metadata

The canonical metadata inputs are `pyproject.toml` for package version and repository identity, and `compatibility.yaml` for KiCad and MCP support policy. `server.json` is the generated registry manifest. `pnpm run metadata:sync` renders the public surfaces, and `pnpm run metadata:check` verifies them in CI and release validation.

## Usage

Use `kicad-mcp-pro --help` to inspect CLI commands and
[`docs/client-configuration.md`](docs/client-configuration.md) to configure an
MCP client. The generated tool catalog is available in
[`docs/tools-reference.generated.md`](docs/tools-reference.generated.md).


## Agent plugin and skills

This repository owns the product-level agent plugin and KiCad-specific skills for
KiCad MCP Pro. The central [`agent-tools`](https://github.com/oaslananka/agent-tools)
repository should catalog this plugin, but the manifest and workflow instructions live
here so they stay synchronized with the actual MCP server tools.

| File | Purpose |
| --- | --- |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Product-level plugin manifest for compatible agent runtimes and marketplace catalogs. |
| [`.mcp.json`](.mcp.json) | Claude Code project-local MCP server configuration. |
| [`.codex/config.example.toml`](.codex/config.example.toml) | Codex CLI MCP configuration example. |
| [`.vscode/mcp.example.json`](.vscode/mcp.example.json) | VS Code / GitHub Copilot workspace MCP configuration example. |
| [`opencode.example.jsonc`](opencode.example.jsonc) | OpenCode project MCP configuration example. |
| [`.opencode/skills/`](.opencode/skills) | OpenCode-native mirrored skill definitions. |
| [`docs/agent-runtime-config.md`](docs/agent-runtime-config.md) | Agent runtime setup and validation matrix. |
| [`skills/kicad-design-review/SKILL.md`](skills/kicad-design-review/SKILL.md) | Comprehensive KiCad design review skill. |
| [`skills/pcb-design/SKILL.md`](skills/pcb-design/SKILL.md) | PCB design, layout inspection, placement, routing, stackup, and board-quality workflow. |
| [`skills/drc-check/SKILL.md`](skills/drc-check/SKILL.md) | ERC/DRC execution, triage, waiver review, and revalidation workflow. |
| [`skills/fabrication-output/SKILL.md`](skills/fabrication-output/SKILL.md) | Manufacturing export, DFM, release evidence, and fabrication-package workflow. |
| [`skills/schematic-review/SKILL.md`](skills/schematic-review/SKILL.md) | Schematic inspection, ERC, connectivity, power, symbol, and readability workflow. |

### Agent setup

KiCad MCP Pro can be launched with the published Python package, npm wrapper, or the
container metadata declared in [`server.json`](server.json). Common local starts are:

```bash
uvx kicad-mcp-pro --transport stdio
uvx kicad-mcp-pro --transport streamable-http --host 127.0.0.1 --port 3334
npx kicad-mcp-pro --help
```

For source checkouts, run the normal repository validation path before publishing plugin
changes:

```bash
corepack pnpm run metadata:check
python3 -m json.tool .claude-plugin/plugin.json >/dev/null
```

### Validation workflow

Before listing this plugin as active from `agent-tools`, verify at least one compatible
agent runtime can:

1. Discover `.claude-plugin/plugin.json`.
2. Launch or connect to `kicad-mcp-pro` over `stdio` or Streamable HTTP.
3. Call `kicad_get_server_info` or `kicad_get_project_info`.
4. Load a skill from `skills/` and follow the workflow without referencing missing tools.
5. Report ERC, DRC, DFM, export artifacts, assumptions, and human-review requirements
   separately.

KiCad MCP Pro is an engineering assistant, not an autonomous manufacturing sign-off
authority. Generated PCB and fabrication outputs require qualified human review before
fabrication or assembly.

## Development

New contributors should start with [`ARCHITECTURE.md`](ARCHITECTURE.md), which maps
the five layers (transport → MCP protocol → orchestration → KiCad adapter seam →
pure domain) and shows exactly how to add a new tool. The runtime model and
quality-gate stack are documented in
[`docs/development/architecture.md`](docs/development/architecture.md).

The project uses a `Taskfile.yml` for common development commands. After
cloning the repository:

```bash
task install     # Install all dependencies (pnpm + uv)
task verify      # Run the local quality gate: lint → format → typecheck → test → build
task test        # Run unit tests only
task lint        # Run lint and metadata checks
task format      # Auto-format the codebase
task typecheck   # Run strict static type checking
task build       # Build release artifacts
task ci          # Run the local equivalent of the full CI pipeline
task hooks       # Install local git hooks
```

All changes must pass `task verify` before opening a pull request.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request. All
changes must pass the repository's format, lint, type-check, test, workflow,
security, and package metadata gates.

## Cite this software

If you use KiCad MCP Pro in research or a technical publication, cite the
archived release via its DOI (see [`CITATION.cff`](CITATION.cff) for full
metadata):

```bibtex
@software{aslan_kicad_mcp_pro,
  author  = {Aslan, Osman},
  title   = {KiCad MCP Pro},
  license = {MIT},
  url     = {https://github.com/oaslananka/kicad-mcp-pro},
  doi     = {10.5281/zenodo.21283791}
}
```

Every GitHub release is archived on Zenodo under this concept DOI, which
always resolves to the most recent version.

## License

KiCad MCP Pro is available under the [MIT License](LICENSE).
