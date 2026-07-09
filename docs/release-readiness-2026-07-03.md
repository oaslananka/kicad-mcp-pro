# July 2026 Release Readiness Evidence

**Review date:** 2026-07-03  
**Release line:** `3.17.1`  
**Repository:** `oaslananka/kicad-mcp-pro`

This document records the release and public-listing evidence used before
external MCP/app-directory submissions. It is intentionally factual: do not mark
an item as complete unless it was verified for the current release line.

## Version and Registry Parity

| Surface | Expected | Verified status | Evidence |
|---|---:|---|---|
| `pyproject.toml` | `3.17.1` | Verified | Local metadata check |
| `package.json` | `3.17.1` | Verified | Local metadata check |
| `server.json` | `3.17.1` | Verified | `pnpm run mcp:manifest:check` |
| `src/kicad_mcp/__init__.py` | `3.17.1` | Verified | Local metadata check |
| PyPI `kicad-mcp-pro` | `3.17.1` | Verified | PyPI JSON API, release present |
| npm `kicad-mcp-pro` | `3.17.1` | Verified | npm registry API, release present |
| GHCR `kicad-mcp-pro:3.17.1` | `3.17.1` | Verified | GHCR v2 manifest API returned an OCI index for linux/amd64 and linux/arm64 |
| GitHub release `mcp-server-v3.17.1` | `3.17.1` | Verified | Release assets include wheel, sdist, SHA256 sums, SBOM, and release-evidence JSON |

## Release Evidence Controls

The latest server release includes the expected Python package artifacts and
release evidence:

- `kicad_mcp_pro-3.17.1-py3-none-any.whl`
- `kicad_mcp_pro-3.17.1.tar.gz`
- `kicad-mcp-pro-python-SHA256SUMS.txt`
- `kicad-mcp-pro-python-sbom.cdx.json`
- `kicad-mcp-pro-python-release-evidence.json`

Container publishing is verified through the registry manifest rather than a
local Docker daemon. The public GHCR manifest for `3.17.1` is an OCI image index
with linux/amd64 and linux/arm64 platform entries.

## Branch and Ruleset Evidence

GitHub repository rulesets report an active ruleset named `main` targeting
branches. The repository intentionally documents a solo-maintainer exception for
mandatory independent human approval. Do not claim OpenSSF Gold or foundation
status while that exception remains active.

## KiCad Baseline Evidence

KiCad MCP Pro treats KiCad `10.0.4` as the current primary stable baseline. The
portable checks that do not require a local KiCad installation passed on this
review:

- `pnpm run metadata:check`
- `pnpm run mcp:manifest:check`
- `pnpm run docs:tools:check`
- `pnpm run parity:check`
- `pnpm run tool-contracts:check`
- `pnpm run compat:check`

The full KiCad CLI contract requires a runtime with `kicad-cli` installed. If the
local environment lacks `kicad-cli`, the release manager must run the KiCad
canary in a KiCad-equipped environment and attach or link the resulting evidence
before treating the canary as release evidence.

## Public Listing Gate

Before submitting to a public directory, run both modes:

```bash
pnpm run submission:check
SUBMISSION_MODE=1 pnpm run submission:check
```

Final submission mode must pass with committed public-listing screenshots. Those
screenshots must not include private board data, customer data, secret values,
local auth state, private absolute paths, or personal usernames.
