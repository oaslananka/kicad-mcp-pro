# Publishing

The canonical source and release authority is
`https://github.com/oaslananka/kicad-mcp-pro`.

All CI/CD, release, registry, package-manager, signing, provenance, and
attestation workflows are owned by that canonical repository.

## PyPI

The canonical Python publication path is `.github/workflows/publish-python.yml`.
Production publishing is triggered only by a `mcp-server-v*` tag and uses the
`pypi` environment. Manual dispatch is limited to TestPyPI from `main` and uses
the `testpypi` environment.

PyPI and TestPyPI Trusted Publisher records must use this exact identity:

- Owner: `oaslananka`
- Repository: `kicad-mcp-pro`
- Workflow: `publish-python.yml`
- Environment: `pypi` or `testpypi`

The workflow builds wheel and source distributions, creates checksums and a
CycloneDX SBOM, emits GitHub artifact attestations, publishes with OIDC, verifies
registry digests, and then checks the PyPI Integrity API publisher identity and statement metadata,
then cryptographically verifies every uploaded file with the pinned
`pypi-attestations` release dependency. Production completion fails
when the package is present but provenance does not match the canonical identity.

### Token fallback

`.github/workflows/publish-python-token.yml` is an emergency-only manual path. It
is restricted to `main`, requires an incident or issue reference, requires an
explicit confirmation input, and is gated by the required reviewer on the
`pypi-token` or `testpypi-token` environment. Token publication does not produce
PEP 740 Trusted Publisher attestations and must not be treated as a normal
release path.

The repository owner is accountable for the fallback project token. Use a
project-scoped token with upload permission only. Rotate it after every use and
at least every 90 days while retained. Revoke it immediately after suspected
exposure, maintainer access changes, unexpected publication, or restoration of a
replacement token. Record the authorization reference and the rotation or
revocation action in the associated private incident record; do not paste token
values into issues, logs, workflow inputs, or release notes.

Before using fallback:

1. record why OIDC is unavailable;
2. confirm the Trusted Publisher owner, repository, workflow, and environment;
3. approve the protected environment deployment;
4. publish and verify registry digests;
5. repair OIDC and prove it with TestPyPI before the next production release.

## GitHub Releases

GitHub Release artifacts are produced by `.github/workflows/release-please.yml`.
Expected release assets include:

- Python wheel and source distribution under `dist/`
- `SHA256SUMS.txt` from the `python-release-evidence` workflow artifact
- `bom.json` SBOM
- Sigstore signing artifacts
- GitHub artifact attestations attached to the release workflow run

Verification guidance lives in
[Release Integrity](security/release-integrity.md).

## GHCR Container Image

Container image publishing is handled by
`.github/workflows/publish-mcp-container.yml` in the canonical repository. The
image name is:

```text
ghcr.io/oaslananka/kicad-mcp-pro
```

The Docker workflow validates the image on pull requests, publishes only for
MCP server release tags such as `mcp-server-v1.1.0`, and pushes multi-arch
`linux/amd64` and `linux/arm64` images to GHCR. Stable releases also update
`ghcr.io/oaslananka/kicad-mcp-pro:latest`; production deployments should use
the release version tag or immutable GHCR digest.

The publish job signs the pushed image digest with Sigstore `cosign`, requests
BuildKit provenance, attaches a BuildKit SBOM, and runs Trivy against the image
digest before signing.

Run the default streamable HTTP image:

```bash
docker run --rm -p 127.0.0.1:3334:3334 \
  -e KICAD_MCP_AUTH_TOKEN="replace-with-strong-32-character-token" \
  ghcr.io/oaslananka/kicad-mcp-pro:<version>
```

Use stdio explicitly for stdio-only MCP clients:

```bash
docker run --rm -i ghcr.io/oaslananka/kicad-mcp-pro:<version> --transport stdio
```

DockerHub publishing is not enabled. The configured DockerHub secrets are
reserved for a future explicitly gated workflow.

## MCP Registry

`server.json` is the official MCP registry manifest. It must remain synchronized with:

- `pyproject.toml` project name and version
- Canonical repository URL
- CLI command `kicad-mcp-pro`
- PyPI package metadata
- GHCR image metadata

Validation commands:

```bash
uv run python scripts/sync_mcp_metadata.py --check
uv run python scripts/validate_mcp_manifest.py
```

Publishing is handled by `.github/workflows/publish-mcp-registry.yml`. The
workflow validates metadata and runs the registry adapter in dry-run mode on
pull requests that touch the MCP server, npm wrapper, or registry workflow
configuration. Real publishing runs only for published GitHub Releases or a
manual workflow dispatch with `dry_run=false`, and uses the protected
`mcp-registry` environment.

If an official target is selected, the workflow uses `mcp-publisher` with
GitHub OIDC. No long-lived token is required for the official target. If a
generic or third-party target is selected without a configured URL, the adapter
fails fast instead of pretending to publish.

## Homebrew

Homebrew tap updates are scaffolded by `.github/workflows/homebrew-publish.yml`
after a GitHub Release is published.

- The workflow creates a pull request against `oaslananka/homebrew-tap`.
- The workflow uses `PACKAGE_MANAGER_TOKEN`.
- The workflow does not push directly to the tap `main` branch.

The formula installs from the PyPI source distribution using Homebrew's Python
virtualenv helper and generated Python resources.

## Scoop

Scoop bucket updates are scaffolded by `.github/workflows/scoop-publish.yml`
after a GitHub Release is published.

- The workflow creates a pull request against `oaslananka/scoop-bucket`.
- The workflow uses `PACKAGE_MANAGER_TOKEN`.
- The workflow does not push directly to the bucket `main` branch.

The manifest references the PyPI wheel for version/hash metadata and installs
the Python package into the Scoop app directory at install time.

## npm Wrapper

The repository root `package.json` is private and exists only for hooks and CI
scripts. It must not be published to npm.

The optional npm wrapper lives under `packages/mcp-npm/`:

```text
packages/mcp-npm/package.json
packages/mcp-npm/bin/kicad-mcp-pro.js
```

The wrapper package name is `kicad-mcp-pro`. It does not install
Python dependencies during the package-manager install lifecycle; at runtime it
executes:

```bash
uvx kicad-mcp-pro
```

`.github/workflows/publish-npm.yml` publishes the wrapper for `mcp-npm-v*`
GitHub Releases and verifies the published tarball digest. Re-running the
workflow for an existing version skips the immutable npm publish operation and
still verifies the existing artifact.

## Required Configuration

Required GitHub environment:

- `mcp-registry`
- `ghcr`

Required GitHub secrets:

- `PACKAGE_MANAGER_TOKEN`

The npm wrapper uses trusted publishing through GitHub Actions OIDC. Do not add
an `NPM_TOKEN` secret for the canonical npm publish workflow.

Required GitHub variables:

- `MCP_REGISTRY_URL` only for generic or third-party registry adapters

## Install Examples

Linux and macOS:

```bash
uvx kicad-mcp-pro
pipx install kicad-mcp-pro
docker run --rm -i ghcr.io/oaslananka/kicad-mcp-pro:<version> --transport stdio
```

Windows PowerShell:

```powershell
uvx kicad-mcp-pro
pipx install kicad-mcp-pro
docker run --rm -i ghcr.io/oaslananka/kicad-mcp-pro:<version> --transport stdio
```

Claude Desktop stdio example:

```json
{
  "mcpServers": {
    "kicad-mcp-pro": {
      "command": "uvx",
      "args": ["kicad-mcp-pro"]
    }
  }
}
```

The CLI can also generate client snippets:

```bash
kicad-mcp-pro mcp-config generate --client claude
kicad-mcp-pro mcp-config generate --client cursor
kicad-mcp-pro mcp-config generate --client vscode
kicad-mcp-pro mcp-config generate --client codex
```

Container stdio example:

```json
{
  "mcpServers": {
    "kicad-mcp-pro": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "ghcr.io/oaslananka/kicad-mcp-pro:<version>",
        "--transport",
        "stdio"
      ]
    }
  }
}
```
