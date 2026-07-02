# Release Integrity

Release integrity controls are emitted only from the canonical repository,
`oaslananka/kicad-mcp`.


## Release evidence target

Current target: **evidence-backed professional release integrity**. The project does not claim a formal SLSA level.

Each release artifact class should provide the strongest evidence supported by its ecosystem: checksums, SBOMs, GitHub artifact attestations, package-registry provenance, container digests, and post-publish verification. A future formal level can be defined per artifact class after the evidence map is stable.

## Python SBOM

The Python publish workflow generates a CycloneDX SBOM as release evidence:

```text
packages/mcp-server/release-evidence/sbom.cdx.json
```

Download it from the GitHub Release or the release workflow artifacts and keep
it with the Python distributions being audited.

## SHA256SUMS

Release checksums are published as workflow evidence, separate from the PyPI
distribution upload directory:

```text
packages/mcp-server/release-evidence/SHA256SUMS.txt
```

In workflow artifacts, download `python-release-evidence` next to the
`python-dist` wheel and source distribution artifacts before verification.

Verify a downloaded artifact:

```bash
sha256sum --check SHA256SUMS.txt
```

On Windows PowerShell:

```powershell
Get-FileHash .\kicad_mcp_pro-<version>-py3-none-any.whl -Algorithm SHA256
```

Compare the hash with the matching line in `SHA256SUMS.txt`.

## Sigstore

The release workflow signs Python distribution artifacts with Sigstore using
GitHub Actions OIDC identity. Verify identity-bound signatures with the Sigstore
CLI:

```bash
python -m sigstore verify identity \
  --cert-identity "https://github.com/oaslananka/kicad-mcp/.github/workflows/release-please.yml@refs/tags/v<version>" \
  --cert-oidc-issuer "https://token.actions.githubusercontent.com" \
  dist/kicad_mcp_pro-<version>-py3-none-any.whl
```

Use the matching tag reference and artifact filename for the release being
verified.

## GitHub Artifact Attestations

The release workflow creates GitHub artifact attestations for release assets.
Verify a local artifact:

```bash
gh attestation verify dist/kicad_mcp_pro-<version>-py3-none-any.whl \
  --repo oaslananka/kicad-mcp
```

For source distributions:

```bash
gh attestation verify dist/kicad_mcp_pro-<version>.tar.gz \
  --repo oaslananka/kicad-mcp
```

## GHCR Image Digest and Provenance

Inspect the published image digest:

```bash
docker buildx imagetools inspect ghcr.io/oaslananka/kicad-mcp-pro:<version>
```

Pull by digest for reproducible deployment:

```bash
docker pull ghcr.io/oaslananka/kicad-mcp-pro@sha256:<digest>
```

Verify the keyless Sigstore signature:

```bash
cosign verify \
  --certificate-identity-regexp "https://github.com/oaslananka/kicad-mcp/.github/workflows/publish-mcp-container.yml@refs/tags/mcp-server-v.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/oaslananka/kicad-mcp-pro@sha256:<digest>
```

The Docker workflow publishes BuildKit provenance and SBOM attestations only
when the image is pushed.

## PyPI Trusted Publishing

The Python publish workflow is configured for PyPI Trusted Publishing through
GitHub Actions OIDC. PyPI and TestPyPI project owners must configure trusted
publishers for the package-index environments:

- Owner: `oaslananka`
- Repository: `kicad-mcp`
- Workflow: `publish-python.yml`
- Environments: `pypi` and `testpypi`

After the publisher is configured, long-lived package-index token secrets should
not be used by CI.

## DockerHub

DockerHub publishing is not enabled. GHCR is the canonical container registry.
If DockerHub support is added later, it must be manual or tag gated, protected by
the `release` environment, and documented with the exact digest and provenance
verification path.


See also [`release-signing.md`](release-signing.md) for artifact-signing and verification policy.
