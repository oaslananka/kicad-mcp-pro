# Release Signing and Verification

KiCad MCP Pro uses artifact-specific release verification instead of relying on maintainer workstation signatures.

## Policy

- Release artifacts are built by GitHub Actions from the canonical repository.
- Publishing jobs use protected environments and job-scoped permissions.
- Release evidence must be generated before publication when supported by the artifact type.
- Users should prefer package-manager provenance, GitHub artifact attestations, checksums, and container signatures over locally-built artifacts from untrusted forks.

## Artifact verification mechanisms

| Artifact | Verification mechanism |
| --- | --- |
| Python wheel and sdist | SHA256 checksums, SBOM, GitHub artifact attestations, PyPI trusted publishing / attestations where supported |
| npm wrapper | npm provenance, SHA256 checksums, SBOM, GitHub artifact attestations |
| Protocol schemas package | npm provenance, SHA256 checksums, SBOM, GitHub artifact attestations |
| Docker image | digest-pinned image references, BuildKit provenance/SBOM, Trivy scan, and keyless cosign signature for GHCR image digests |
| GUI bundles | SHA256 checksums, Cargo-lock CycloneDX SBOM, GitHub artifact attestation, exact published-asset verification, and explicit platform-signing status |

GitHub artifact attestations bind GUI installer digests and the SBOM to the canonical workflow identity. They do **not** replace Authenticode, Apple code signing/notarization, or Linux package-repository signing. Until vendor signing credentials are configured, the GUI evidence records those platform-signing states as unsigned/unnotarized rather than implying a stronger guarantee.

## Maintainer checklist

Before publishing a release:

1. Confirm the release commit is on `main` and all required checks passed.
2. Confirm generated version metadata and package manifests agree.
3. Confirm checksums, SBOMs, and attestations were created or that the exception is documented.
4. Confirm package-manager publish jobs use trusted publishing, OIDC, or a protected environment.
5. Confirm release notes do not overclaim KiCad or EDA sign-off coverage.

## User verification guidance

Users should verify artifacts by:

- installing from official package registries or GHCR;
- using immutable version tags or image digests;
- checking release checksums when downloading artifacts manually;
- using `gh attestation verify` for attested artifacts;
- using `cosign verify` for signed container images.

See [`release-integrity.md`](release-integrity.md) for command examples.
