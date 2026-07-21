# Reproducible Development Bootstrap Design

## Goal

Provide one repository-owned, rootless Linux bootstrap command that installs the pinned development toolchain into checkout-local roots, performs frozen dependency installation, and produces diagnostics that clearly separate required development tools, optional GUI-development tools, and live KiCad capabilities.

## Scope and constraints

- Supported bootstrap host: glibc-based Linux on `x86_64` or `aarch64` with `bash`, `curl`, `tar`, `xz`, and `sha256sum` available.
- No write to system package directories, global npm prefixes, global Python locations, global Rust homes, or user-wide tool-manager state.
- Exact versions come from a committed toolchain contract and all downloaded native archives are checked against committed SHA-256 values.
- Core required tools are Python, uv, Node.js, and pnpm.
- Task, Rust, and Cargo are development-optional but installed by the default full bootstrap because they are needed by repository convenience tasks and the Tauri bridge.
- KiCad CLI and live GUI/IPC are capability probes, not bootstrap-installed system software. Missing KiCad must yield an explicit limited-capability result rather than an unexplained failure.
- Existing package, workflow, and release-security policies remain in force.

## Architecture

### Toolchain contract

`scripts/dev-toolchain.env` is a shell-compatible, data-only contract containing exact versions and Linux archive checksums for uv, Node.js, Task, and rustup. `.python-version` is promoted to the exact managed Python patch version. `rust-toolchain.toml` pins the Rust compiler used for Tauri checks. The contract is parsed by diagnostics and sourced by the bootstrap script.

### Rootless bootstrap

`scripts/bootstrap-dev.sh` resolves the repository root, validates the host architecture and required system utilities, and creates `.dev-tools/`, `.dev-cache/`, `.venv/`, and a relocatable `.dev-env.sh`.

It installs and verifies exact uv, Python, Node.js, pnpm, Task, rustup, Rust, and Cargo versions. It then runs `uv sync --all-extras --frozen` and `pnpm install --frozen-lockfile`. Re-running the script is idempotent. `--check` performs no downloads and verifies the prepared environment. `--ci` additionally runs the repository development doctor and the agreed quality gates. `--core-only` omits Task/Rust installation while preserving an explicit optional-tool diagnostic.

### Development doctor

The public doctor report gains an optional `development` section when executed from a source checkout. It reports:

- capability mode: `core-only`, `headless-kicad`, or `gui-connected`,
- each tool's classification (`required`, `optional`, or `live-kicad`), expected and detected version, executable path, status, and exact remediation command,
- writable tool/cache/virtual-environment roots,
- frozen dependency readiness.

The existing non-strict doctor remains non-fatal for normal missing KiCad GUI/IPC. The source-checkout command `pnpm run dev:doctor -- --ci` fails only when required tools, writable roots, or frozen dependency readiness are invalid; optional and live-KiCad limitations remain structured warnings.

### Clean-host evidence

A path-filtered GitHub Actions workflow starts with a clean HOME and repository-local caches, runs the bootstrap without root access for the toolchain, validates exact versions, and executes metadata, formatting, lint, typecheck, unit tests, and package checks. A second job installs the supported KiCad CLI using the runner's package facility, activates the same bootstrapped environment, and runs the stable KiCad canary. Artifacts contain redacted doctor JSON and bootstrap logs.

## Error handling and recovery

Every download is written to a temporary file, checksum-verified, then atomically moved into its versioned destination. Unsupported operating systems, architectures, missing system prerequisites, checksum mismatches, version drift, unwritable roots, and frozen-lock failures produce distinct messages with recovery commands. Cleanup removes only `.dev-tools`, `.dev-cache`, `.venv`, and `.dev-env.sh`. Upgrade means changing the committed contract and checksums in a reviewed PR, never self-updating during bootstrap.

## Testing

- Unit tests parse and validate the toolchain contract.
- Bootstrap tests use temporary fake archives and command shims to prove root containment, checksum failure, idempotency, and `--check` behavior without network access.
- Doctor tests cover required/optional/live classifications, exact version mismatches, writable roots, and headless versus GUI-connected capability modes.
- Workflow-policy tests require SHA-pinned Actions and verify the clean-host workflow contract.
- The live workflow supplies real clean-host and KiCad-canary evidence before merge.

## Out of scope

- Installing desktop KiCad without the host package manager.
- Supporting Windows or macOS bootstrap in this change.
- Replacing uv, pnpm, Task, or rustup with a new global version manager.
- Treating a headless CLI environment as equivalent to a live KiCad GUI session.
