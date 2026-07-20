# Release

## Safe live-preview hardening

The live-preview workflow is now documented as a safe artifact-first agent feedback loop.

Current product versions are represented in:

- `.release-please-manifest.json`
- `pyproject.toml`
- `src/kicad_mcp/__init__.py`
- `src/kicad_mcp/server.json`
- `packages/mcp-npm/package.json`
- `packages/protocol-schemas/package.json`

`.release-please-manifest.json` tracks product package paths only. The private repository root is not released.

Release PRs are created by `.github/workflows/release-please.yml` with separate Release Please pull requests per product package path. The VS Code extension (KiCad Studio) releases independently from its own repository; `kicad-mcp-pro` Python package and npm launcher stay version-linked as one MCP product. Python production publishing runs from `mcp-server-v*` tag pushes through the protected `pypi` environment; manual Python publishing is limited to TestPyPI.

The publish workflows keep release evidence product-scoped:

- `publish-python.yml` validates the wheel and source distribution, emits
  `release-evidence/SHA256SUMS.txt`, emits a CycloneDX SBOM,
  uploads that evidence as `python-release-evidence`, and creates GitHub
  artifact attestations for the Python wheel and source distribution before PyPI
  trusted publishing. The publish jobs verify local checksums before upload and
  verify PyPI/TestPyPI SHA-256 digests after upload, and require a matching PyPI Integrity API Trusted Publisher identity and
  cryptographically verified PEP 740 attestation for each distribution. The
  `python-dist` artifact intentionally contains only `*.whl` and `*.tar.gz` files.
- `publish-npm.yml` packs the `kicad-mcp-pro` npm launcher tarball, emits
  `SHA256SUMS.txt` and a CycloneDX SBOM, creates GitHub artifact attestations,
  publishes with npm provenance, and downloads the published tarball to verify
  its SHA-256 digest.
- `publish-mcp-container.yml` validates the Docker image on pull requests and
  publishes signed multi-arch GHCR images with BuildKit SBOM/provenance for
  `mcp-server-v*` GitHub Releases.
- `publish-protocol-schemas.yml` publishes `@oaslananka/kicad-protocol-schemas`
  for `protocol-schemas-v*` GitHub Releases.

Release dry-runs also validate `compatibility.yaml` through the MCP server release preflight. Update [docs/status/runtime-policy-matrix.md](status/runtime-policy-matrix.md) and release notes whenever KiCad, VS Code, MCP, Node, pnpm, Python, or tool-schema support changes.

## Conventional Commit Scopes

Release Please derives product changelogs from Conventional Commits, so pull request titles and product-changing commits must use one of these scopes:

- `kicad-studio` for the VS Code extension (separate repository).
- `kicad-mcp-pro` for `src/kicad_mcp` and `packages/mcp-npm`.
- `repo` for repository governance, documentation, workflow, and shared release policy changes.
- `deps` for dependency-only updates.

Commits that touch both product directories must be split by product or use the multi-scope form `kicad-studio/kicad-mcp-pro`. Release Please generated PRs retain their upstream `chore(main): release ...` title format and are exempt from the human PR title scope gate.

Run product dry-runs before merging release-related changes:

```bash
corepack pnpm run release:dry-run
corepack pnpm run check:release-please
```
