# Release Integrity

Release integrity controls are emitted only from the canonical repository,
`oaslananka/kicad-mcp-pro`.


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
  --cert-identity "https://github.com/oaslananka/kicad-mcp-pro/.github/workflows/publish-python.yml@refs/tags/mcp-server-v<version>" \
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
  --repo oaslananka/kicad-mcp-pro
```

For source distributions:

```bash
gh attestation verify dist/kicad_mcp_pro-<version>.tar.gz \
  --repo oaslananka/kicad-mcp-pro
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
  --certificate-identity-regexp "https://github.com/oaslananka/kicad-mcp-pro/.github/workflows/publish-mcp-container.yml@refs/tags/mcp-server-v.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/oaslananka/kicad-mcp-pro@sha256:<digest>
```

The Docker workflow publishes BuildKit provenance and SBOM attestations only
when the image is pushed.

## GUI installer integrity

The Tauri GUI release workflow builds the Linux, Windows, and macOS installers from the exact `kicad-mcp-gui-v*` tag commit and publishes three evidence files with the installers:

```text
kicad-mcp-pro-gui-SHA256SUMS.txt
kicad-mcp-pro-gui-sbom.cdx.json
kicad-mcp-pro-gui-release-evidence.json
```

The evidence JSON records the source commit, release tag, normalized installer inventory, platform classification, size, SHA-256 digest, and the actual platform-signing status. The CycloneDX 1.6 SBOM is generated deterministically from the committed `src-tauri/Cargo.lock`. Before publication the workflow verifies the installer directory against the generated evidence; after upload it downloads the GitHub Release assets and requires the published inventory and installer digests to match exactly.

Verify a downloaded GUI installer with the published checksum file and GitHub attestation:

```bash
sha256sum --check kicad-mcp-pro-gui-SHA256SUMS.txt
gh attestation verify <installer-file> --repo oaslananka/kicad-mcp-pro
```

The GitHub attestation proves CI/source provenance for the installer digest; it is not a substitute for platform code signing. Windows Authenticode, Apple code signing/notarization, and Linux package signing remain separately reported and must not be inferred from the GitHub attestation.

## PyPI Trusted Publishing

The Python workflow uses short-lived GitHub OIDC credentials and PyPI Trusted
Publishing. The required publisher identities are:

| Index | Repository | Workflow | Environment | Allowed ref |
| --- | --- | --- | --- | --- |
| PyPI | `oaslananka/kicad-mcp-pro` | `publish-python.yml` | `pypi` | tag `mcp-server-v*` |
| TestPyPI | `oaslananka/kicad-mcp-pro` | `publish-python.yml` | `testpypi` | branch `main` |

Repository renames change the OIDC identity. Update both PyPI and TestPyPI
Trusted Publisher records before publishing from a renamed repository. A
publisher record for the former repository name is not accepted as current
provenance.

After upload, the workflow queries the PyPI Integrity API for every wheel and
source distribution. It requires a PEP 740 publish attestation whose digest, repository,
workflow, and environment match the expected release identity. The pinned
`pypi-attestations` verifier then validates the Sigstore-backed attestation
cryptographically against the canonical repository. A
matching file digest without matching Trusted Publisher provenance is a release
failure.

Independent verification can use the PyPI attestations CLI:

```bash
pypi-attestations verify pypi \
  --repository https://github.com/oaslananka/kicad-mcp-pro \
  https://files.pythonhosted.org/.../kicad_mcp_pro-<version>-py3-none-any.whl
```

The token fallback is emergency-only and cannot produce the Trusted Publisher
publish attestation. Its successful digest verification does not satisfy the
normal provenance requirement.

## DockerHub

DockerHub publishing is not enabled. GHCR is the canonical container registry.
If DockerHub support is added later, it must be manual or tag gated, protected by
the `release` environment, and documented with the exact digest and provenance
verification path.


See also [`release-signing.md`](release-signing.md) for artifact-signing and verification policy.
