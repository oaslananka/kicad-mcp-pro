# Publishing

The canonical source and release authority is
`https://github.com/oaslananka/kicad-mcp-pro`.

All CI/CD, release, registry, package-manager, signing, provenance, and
attestation workflows are owned by that canonical repository.

## PyPI

Python package releases use `.github/workflows/release-please.yml` in
`oaslananka/kicad-mcp-pro`. The workflow builds the Python distributions,
creates release artifacts, generates SBOM and checksum files, signs artifacts
with Sigstore, creates GitHub artifact attestations, and publishes to PyPI only
when release-please reports that a release was created and the protected
`release` environment is approved.

The release workflow uses PyPI Trusted Publishing through GitHub Actions OIDC.
Long-lived package-index token secrets should not be needed once the PyPI
trusted publisher is configured.

### Token fallback (manual, OIDC unavailable)

`.github/workflows/publish-python-token.yml` is a manual-only
(`workflow_dispatch`) fallback for when trusted publishing cannot run — most
commonly right after a repository rename, before the PyPI/TestPyPI
trusted-publisher configuration is updated to the new repository name (the OIDC
claim carries the new name while PyPI still expects the old one, so the primary
path fails).

The preferred fix is to update the trusted publisher's repository name on PyPI
and TestPyPI and return to the OIDC path. The token fallback exists only to
unblock a publish in the meantime. Note that token authentication cannot mint
PEP 740 attestations.

To use it: create the gated environments `pypi-token` and `testpypi-token` (add
required reviewers), then add an environment secret named `PYPI_PUBLISH_TOKEN`
to each — the real PyPI project token on `pypi-token`, the TestPyPI project
token on `testpypi-token`. Run the workflow and pick the `target`; the chosen
environment supplies the matching token. Use project-scoped tokens, not
account-wide ones.

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
