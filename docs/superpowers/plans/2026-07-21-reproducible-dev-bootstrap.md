# Reproducible Development Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a rootless, repository-scoped Linux development bootstrap and an explicit required/optional/live-KiCad doctor report for issue #406.

**Architecture:** A committed toolchain contract drives a checksum-verifying Bash bootstrap and Python diagnostics. Tool binaries and caches remain under checkout-local ignored roots, while a dedicated workflow proves a clean-host bootstrap and a supported KiCad canary.

**Tech Stack:** Bash, Python 3.13/Pydantic, uv, Node.js, pnpm, Task, rustup/Rust, pytest, GitHub Actions.

## Global Constraints

- Support glibc Linux `x86_64` and `aarch64` only in this iteration.
- Never write to system or user-global tool directories.
- Pin Python `3.13.12`, uv `0.10.8`, Node.js `24.11.0`, pnpm `11.5.0`, Task `3.52.0`, rustup `1.29.0`, and Rust `1.97.1`.
- Verify every downloaded native archive with a committed SHA-256 value.
- Keep missing KiCad CLI/GUI non-fatal outside strict live-capability checks.
- All GitHub Actions must use full commit SHAs and pass repository workflow policy.

---

### Task 1: Pin and validate the development toolchain contract

**Files:**
- Create: `scripts/dev-toolchain.env`
- Create: `scripts/dev_environment.py`
- Create: `rust-toolchain.toml`
- Modify: `.python-version`
- Modify: `.gitignore`
- Create: `tests/unit/test_dev_toolchain.py`

**Interfaces:**
- Produces: `load_toolchain_contract(root: Path) -> DevToolchainContract` in `scripts/dev_environment.py` for later tasks.

- [ ] Write tests that require exact versions, both supported Linux architectures, 64-character lowercase SHA-256 values, and agreement with `.python-version`, `package.json`, `uv.toml`, and `rust-toolchain.toml`.
- [ ] Run `uv run pytest tests/unit/test_dev_toolchain.py -q` and confirm failure because the contract/parser do not exist.
- [ ] Implement the data-only contract and minimal parser/validator.
- [ ] Re-run the focused tests and confirm success.
- [ ] Commit with `chore(dev): pin repository toolchain contract`.

### Task 2: Implement the rootless bootstrap

**Files:**
- Create: `scripts/bootstrap-dev.sh`
- Extend: `scripts/dev_environment.py`
- Create: `tests/unit/test_dev_bootstrap.py`
- Modify: `package.json`
- Modify: `Taskfile.yml`

**Interfaces:**
- Consumes: validated toolchain contract from Task 1.
- Produces: `.dev-env.sh`, `.dev-tools/`, `.dev-cache/`, `.venv/`, and commands `dev:bootstrap` and `dev:doctor`.

- [ ] Write fake-download/shim tests proving checkout-local destinations, checksum rejection, idempotent re-entry, `--check`, and `--core-only` behavior.
- [ ] Run the bootstrap tests and confirm they fail because the script is absent.
- [ ] Implement host validation, atomic checksum-verified installs, relocatable environment activation, exact managed Python, frozen uv/pnpm sync, and check/CI modes.
- [ ] Add package and Task aliases without introducing a new package manager.
- [ ] Run focused bootstrap tests and shell syntax checks.
- [ ] Commit with `feat(dev): add rootless repository bootstrap`.

### Task 3: Expand doctor with development capability diagnostics

**Files:**
- Modify: `src/kicad_mcp/diagnostics.py`
- Modify: `tests/unit/test_cli_diagnostics.py`
- Modify: `tests/unit/test_doctor_config_diagnostics.py`
- Extend: `scripts/dev_environment.py`

**Interfaces:**
- Consumes: toolchain contract and prepared-root conventions.
- Produces: `DevelopmentDiagnostics` embedded in `DiagnosticReport.development` and a source-checkout doctor CLI policy.

- [ ] Write tests for required/optional/live classifications, expected/actual versions, remediation commands, writable roots, and `core-only`/`headless-kicad`/`gui-connected` modes.
- [ ] Confirm the new tests fail against the current report.
- [ ] Implement the Pydantic models and non-fatal probes without exposing secrets.
- [ ] Implement CI policy that fails only for required-development errors.
- [ ] Run all doctor/setup tests and JSON bundle/schema tests.
- [ ] Commit with `feat(doctor): report reproducible development capabilities`.

### Task 4: Add clean-host and KiCad-canary evidence

**Files:**
- Create: `.github/workflows/dev-bootstrap.yml`
- Modify: `.github/actions-policy.json` only if a job requires a write permission (expected: none)
- Modify: `tests/unit/test_release_hardening.py`

**Interfaces:**
- Consumes: bootstrap and doctor commands.
- Produces: clean-host bootstrap logs, doctor JSON, quality-gate results, and supported KiCad canary evidence.

- [ ] Add a failing workflow-contract test requiring clean HOME, no sudo in the core bootstrap job, exact version assertions, frozen installs, quality gates, a separate KiCad canary job, and uploaded evidence.
- [ ] Implement the SHA-pinned workflow with read-only permissions and path filters.
- [ ] Run workflow policy, actionlint, Zizmor, and focused workflow tests.
- [ ] Commit with `ci(dev): verify bootstrap on clean hosts`.

### Task 5: Document operation and recovery

**Files:**
- Create: `docs/development/reproducible-bootstrap.md`
- Modify: `README.md`
- Modify: `docs/installation.md`
- Modify: `mkdocs.yml` if navigation is explicit.
- Modify: `tests/unit/test_release_hardening.py`.

**Interfaces:**
- Documents the exact one-command setup, capability modes, cleanup, upgrade, checksum failure recovery, and KiCad GUI limitations.

- [ ] Add tests that reject the stale missing `dev:doctor` documentation contract and require cleanup/recovery commands.
- [ ] Write focused operational documentation and replace ambiguous global-tool-manager guidance.
- [ ] Run strict documentation build and link checks.
- [ ] Commit with `docs(dev): document bootstrap recovery and capability modes`.

### Task 6: End-to-end verification and PR

**Files:** All changed files from Tasks 1–5.

- [ ] Run `scripts/bootstrap-dev.sh --check` against a prepared environment.
- [ ] Run doctor/setup/dev-toolchain/bootstrap focused tests.
- [ ] Run metadata, format, lint, mypy, unit tests, package checks, workflow policy, actionlint, Zizmor, and strict docs build.
- [ ] Run the actual bootstrap in an empty HOME and repository-local tool/cache roots.
- [ ] Commit any evidence-only corrections without weakening tests.
- [ ] Push the branch and open a PR linked to #406.
- [ ] Wait for clean-host, KiCad canary, OS matrix, CodeQL, dependency review, Gitleaks, Socket, Codecov, and Required PR Gate.
- [ ] Inspect all bot/agent comments, reviews, inline comments, and review threads; address every actionable item.
- [ ] Squash merge only when the final HEAD is clean, then verify post-merge main workflows and close #406 with public evidence links.
