# KiCad PCM and Guided Onboarding Design

## Context

Issue #731 turns the existing `packages/kicad-plugin` companion into a real KiCad Plugin and Content Manager (PCM) distribution/onboarding surface without creating a second MCP implementation. The current companion is a legacy `pcbnew.ActionPlugin`, is manually copied into KiCad, and talks only to the canonical loopback MCP backend. The repository already has mature backend health, setup/config generation, backup/restore, release provenance, and client-specific configuration support.

Fresh review found three concrete safety/product gaps that belong in this issue:

1. `setup.write_config()` backs up an existing client config and then overwrites the whole file, so unrelated client settings can be lost.
2. `setup_agent()` invokes Claude Code's native `claude mcp add` path even in preview mode, so a nominally read-only setup preview may mutate external configuration.
3. `kicad-mcp-pro init` defaults to writing configuration, so non-interactive use does not require an explicit write opt-in.

The existing companion uses SWIG `pcbnew.ActionPlugin`; it is not a modern KiCad IPC-runtime plugin. KiCad PCM v2 supports an explicit `runtime` field with `swig` and `ipc`. The first package must therefore declare `runtime: "swig"` and keep modern plugin API migration as a documented readiness path rather than misrepresenting the implementation.

## Goals

1. Produce a deterministic, versioned KiCad PCM v2 package from repository-owned source.
2. Preserve the companion/backend boundary: the PCM package remains a thin local companion; the canonical MCP backend remains `kicad-mcp-pro`.
3. Add machine-readable plugin/backend compatibility and fail closed on incompatible versions.
4. Reuse the existing unauthenticated loopback `/api/health` endpoint for actionable in-KiCad status.
5. Make guided client configuration explicit, merge-safe, validated, backed up, atomic, and reversible for Claude Code, Codex, Cursor, and existing maintained formats.
6. Publish PCM release assets with checksums and GitHub attestation using the repository's existing release pattern.
7. Validate clean install/connect/MCP smoke/update/incompatible/uninstall/rollback on real KiCad where the maintained host matrix is available, and document any unverified platform honestly.
8. Keep `uvx kicad-mcp-pro` first-class and unchanged.

## Non-goals

- No second MCP server inside the plugin.
- No public listener or automatic network exposure.
- No silent credential creation/storage.
- No automatic client-config mutation from PCM installation.
- No weakening of existing write approvals.
- No claim that the current ActionPlugin is a modern IPC plugin.
- No official KiCad addon-repository submission until the package artifact and public release URL exist and the official metadata can truthfully contain final download digest/size fields.
- No paid external service or new runtime dependency.

## Architecture

### 1. Deterministic PCM builder

Add `scripts/build_kicad_pcm.py` plus repository-owned package metadata under `packaging/kicad-pcm/`.

The builder reads the canonical package version from `pyproject.toml` and emits an ISO-compatible ZIP with sorted entries, fixed timestamps, deterministic permissions, and exactly the reviewed package tree:

```text
metadata.json
plugins/__init__.py
plugins/context.py
plugins/kicad_mcp_companion.py
plugins/compatibility.json
```

The internal `metadata.json` uses KiCad PCM schema v2 and one version entry only. It must not include repository-only `download_url`, `download_sha256`, `download_size`, or `install_size` fields. The package runtime is `swig`, minimum KiCad is `10.0`, and package identifier is `com.github.oaslananka.kicad-mcp-pro` after uniqueness validation against the official metadata repository.

The builder also emits a checksum/evidence JSON next to the archive. Build validation is offline and does not depend on fetching the KiCad schema during CI.

### 2. Compatibility contract

`plugins/compatibility.json` is generated from the root version and contains a small closed schema owned by this repository. The initial policy is same-major-and-minor compatibility because release-please keeps the backend and companion on the same product release train.

Example shape:

```json
{
  "schema_version": "kicad-mcp-companion-compat.v1",
  "plugin_version": "3.33.3",
  "backend": {
    "minimum": "3.33.0",
    "maximum_exclusive": "3.34.0"
  },
  "kicad": {
    "minimum": "10.0",
    "runtime": "swig"
  }
}
```

The companion parses numeric semantic-version triplets with standard-library code. Missing/malformed compatibility metadata or an out-of-range backend version fails closed and returns actionable status rather than attempting a mutating workflow.

### 3. Backend health in the companion

Extend the shared companion `StudioContextClient` with a loopback-only `GET /api/health` call. No new backend endpoint is added. The existing endpoint already returns health and backend version and is intentionally unauthenticated even when the MCP transport uses a bearer token.

A pure status classifier returns one of a closed set:

- `ready`
- `backend_unreachable`
- `backend_unhealthy`
- `backend_incompatible`
- `authentication_required`
- `runtime_unavailable`

The ActionPlugin presents these states in KiCad using existing `wx.MessageBox` behavior and concrete recovery guidance. Context push only proceeds when compatibility/health permit it.

### 4. Client configuration transaction

Keep existing client-specific generators in `setup.py`; do not add a parallel config system.

For JSON clients, merge only the owned server-map key:

- `mcpServers` for Claude/Cursor/Gemini/etc.
- `servers` for VS Code.
- `mcp` for OpenCode.

Preserve all unrelated top-level keys and other server entries. If an existing file is invalid, fail before any mutation.

For Codex TOML, replace only the owned `[mcp_servers.kicad]` and `[mcp_servers.kicad.env]` sections, preserving unrelated tables/comments/text. No TOML dependency is added.

All file writes follow:

1. resolve target;
2. read existing content;
3. compute merged content in memory;
4. validate merged content;
5. if an existing conflicting `kicad` entry differs, require the caller's explicit approved write path; preview never mutates;
6. create a timestamped backup when the target exists;
7. write a same-directory temporary file;
8. atomically `os.replace()` it into place;
9. validate the persisted file;
10. leave the backup available for `setup-restore`.

Claude Code native CLI installation executes only under `write=True`. `kicad-mcp-pro init` defaults to print/preview and requires `--write` for mutation.

### 5. Release integration

Add a narrowly scoped PCM publication workflow following `publish-mcpb.yml`:

- trigger only for `mcp-server-v*` published releases and explicit backfill dispatch;
- verify tag, source commit, and version alignment;
- build deterministic PCM artifact from the tagged source;
- generate SHA256/evidence;
- attest the checksum using `actions/attest` with only `contents: write`, `id-token: write`, `attestations: write`, and `artifact-metadata: write` as required;
- upload the PCM ZIP and evidence to the existing GitHub Release;
- re-download and verify the published digest.

PR CI only validates the builder/metadata/workflow contract; it never publishes.

### 6. Real KiCad evidence

Use a disposable fixture-safe Windows test environment on KiCad 10.0.5 to validate:

1. PCM `Install from File` from the built ZIP (no manual plugin copy).
2. KiCad restart and companion discovery.
3. backend absent/unreachable status.
4. compatible backend health.
5. one explicit guided client config flow against a disposable config fixture, plus unit-level transactions for Claude Code, Codex, and Cursor.
6. MCP initialize -> initialized -> tools/list and one read-only context/tool call.
7. compatible update/reinstall.
8. forced incompatible backend-version fixture fails closed.
9. uninstall removes plugin package while preserving unrelated client config.
10. rollback/reinstall of the previously trusted package succeeds.

Host/user configuration is snapshotted before validation and restored after it. Evidence must be sanitized and avoid private absolute paths, credentials, socket tokens, or unrelated desktop content.

macOS/Linux are reported only from actual package/CI/real-host evidence available in this tranche; no platform is marked verified from file presence alone.

## Security and compatibility

- PCM package talks only to loopback HTTP(S), preserving existing SSRF/public-exposure protections.
- `/api/health` contains no secret and remains the only unauthenticated status dependency.
- Existing auth token behavior for MCP tool calls is unchanged.
- Existing public MCP tools/schemas are unchanged.
- `uvx`, PyPI, npm, Docker, desktop, MCPB remain unchanged.
- Existing client config is never replaced wholesale by the guided setup path.
- Invalid existing config or atomic-write failure leaves the original untouched.
- Backups contain local user configuration and must never be committed as evidence.

## Verification boundary

The issue closes only after all of the following are true on the PR's exact head:

- deterministic PCM package contract and workflow tests pass;
- setup/config transaction tests prove preview is side-effect-free and write is narrow/reversible;
- companion health/compatibility tests pass;
- Ruff, format, mypy, Bandit, build, release/workflow policy, full tests/coverage, Sonar, CodeQL, Codecov and required PR gate pass;
- real KiCad install/connect/MCP/read/update/incompatible/uninstall/rollback evidence is committed in sanitized form;
- distribution/readiness docs link only objective evidence;
- final reviewer pass finds no secret/temp/generated-untracked/config drift.
