# Reproducible development bootstrap

The repository provides a rootless Linux bootstrap for contributors and CI. It
installs the exact reviewed toolchain into the checkout instead of modifying
system package directories, a global npm prefix, or user-wide Python and Rust
homes.

## Supported hosts

The bootstrap currently supports glibc-based Linux on `x86_64` and `aarch64`.
The host must already provide `bash`, `python3`, TLS certificate roots, and the
standard archive libraries used by Python. KiCad is intentionally not installed
by the core bootstrap because it is host software with GUI and system-library
requirements.

## One-command setup

From a fresh clone:

```bash
./scripts/bootstrap-dev.sh
source .dev-env.sh
pnpm run dev:doctor -- --ci
```

The first command installs the exact versions committed in
`scripts/dev-toolchain.env`:

- Python 3.13.12
- uv and uvx 0.11.31
- Node.js 24.11.0
- pnpm 11.5.0
- Task 3.52.0
- rustup 1.29.0
- Rust, Cargo, and rustfmt 1.97.1

The same contract records Tauri CLI 2.11.4 for GUI release jobs. The bootstrap
does not install that CLI globally; release automation installs the reviewed
version with Cargo and verifies the committed `src-tauri/Cargo.lock` before
building installers.

Native downloads are written to temporary files, checked against committed
SHA-256 values, and only then moved into `.dev-tools/`. Python and Node
dependencies are installed from the committed lock files using frozen mode.
Re-running the command is idempotent.

The generated `.dev-env.sh` is relocatable within the checkout. Source it in
each new shell before running repository commands:

```bash
source .dev-env.sh
pnpm run test:unit
```

## Verification modes

Verify an existing prepared checkout without downloading or changing it:

```bash
./scripts/bootstrap-dev.sh --check
./scripts/bootstrap-dev.sh --check --json
```

Install only the required Python/uv/Node/pnpm toolchain when Task and Tauri
Rust work are not needed:

```bash
./scripts/bootstrap-dev.sh --core-only
```

Run the clean-host acceptance gates after preparation:

```bash
./scripts/bootstrap-dev.sh --core-only --ci --json
```

That mode runs metadata synchronization checks, formatting, lint, type checks,
unit tests, and package validation with the bootstrapped binaries. A missing
KiCad CLI is recorded as a live-capability limitation rather than silently
being treated as a successful KiCad integration test.

## Doctor and capability modes

Run the source-checkout doctor after sourcing the environment:

```bash
pnpm run dev:doctor -- --ci
pnpm --silent run dev:doctor -- --json --ci
```

The development section separates three classes:

- **required** — Python, uv, uvx, Node.js, and pnpm; a missing or mismatched
  required tool fails `--ci`;
- **optional** — Task, Rust, and Cargo; missing tools are explicit limitations
  and can be restored by running the full bootstrap;
- **live-kicad** — KiCad CLI and GUI/IPC connectivity; these are host
  capabilities rather than repository-downloaded tools.

The reported capability mode is:

- `core-only` when no supported KiCad CLI is available;
- `headless-kicad` when the CLI is available but no live GUI/IPC board session
  can be reached;
- `gui-connected` when the live KiCad IPC session is reachable.

A `headless-kicad` result can run CLI exports and the stable canary. It is not
proof that a desktop GUI session, current board, or live schematic context is
available.

## State locations

The bootstrap owns only these ignored paths:

| Path | Purpose |
| --- | --- |
| `.dev-tools/` | Versioned native binaries and managed Python/Rust runtimes |
| `.dev-cache/` | uv, npm, pnpm, Corepack, and download caches |
| `.venv/` | Frozen Python environment for this checkout |
| `.dev-env.sh` | Generated activation file |
| `node_modules/` | Frozen pnpm workspace installation |

No secret is written to the toolchain contract or the generated environment
file.

## Recovery

### SHA-256 mismatch

A message containing `SHA-256 mismatch` means the downloaded bytes do not match
the reviewed contract. Do not bypass the check. Remove the affected cached
archive and retry on a trusted network. If the upstream release was legitimately
replaced, update the version and checksum together in a reviewed pull request.

```bash
rm -rf .dev-cache/downloads
./scripts/bootstrap-dev.sh
```

### Interrupted or partial installation

The installer detects incomplete versioned destinations and reconstructs them.
A full local reset removes only repository-owned state:

```bash
rm -rf .dev-tools .dev-cache .venv .dev-env.sh node_modules
./scripts/bootstrap-dev.sh
```

### Version mismatch

Use the machine-readable check to identify the mismatched executable:

```bash
./scripts/bootstrap-dev.sh --check --json
```

Do not use `uv self update`, a global `npm install -g`, or a global tool manager
to repair this checkout. Re-run the repository bootstrap so the committed
contract remains the source of truth.

### Missing KiCad

Install the supported stable KiCad release with the host package manager, then
verify:

```bash
kicad-cli version
source .dev-env.sh
pnpm run test:kicad-cli-contract
```

The stable baseline remains KiCad 10.0.5 until the compatibility matrix is
updated in a reviewed change. A CLI-only host remains `headless-kicad`; start
KiCad, enable IPC, and open a board to reach `gui-connected` mode.

## Upgrading the toolchain

Tool upgrades are code changes. Update `scripts/dev-toolchain.env`, the related
repository pin such as `.python-version`, `uv.toml`, `package.json`, or
`rust-toolchain.toml`, and the committed checksums in one pull request. Rust
application dependency updates must refresh `src-tauri/Cargo.lock` in the same
change and pass Cargo's locked metadata/check gates. The contract tests,
clean-host workflow, OS matrix, and security checks must pass on the final
commit before merge.
