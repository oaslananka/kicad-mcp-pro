# Release and Supply-Chain Security

This document defines the security posture expected for KiCad MCP Pro releases, package publishing, and distribution artifacts.

## Goals

- Releases are built from the canonical `oaslananka/kicad-mcp-pro` repository.
- Publishing happens through GitHub Actions, not from a maintainer workstation.
- Long-lived package-manager tokens are avoided where trusted publishing or OIDC is available.
- Release artifacts are reproducible enough to verify names, versions, checksums, SBOMs, and provenance.
- Public claims are evidence-backed: if a capability is heuristic, partial, or environment-dependent, the release notes and docs say so.

## Protected release path

The normal release path is documented in [`../release-process.md`](../release-process.md). The required posture is:

1. Work lands through pull requests to `main`.
2. Required CI, security, CodeQL, docs, and metadata checks pass.
3. Release-please derives versions from Conventional Commits and opens the release pull request.
4. Production Python publishing runs only from canonical `mcp-server-v*` tag pushes; manual dispatch is TestPyPI-only.
5. Protected environments gate publishing jobs.
6. Publish jobs produce or verify release evidence before publishing.
7. Post-publish verification confirms the package-index artifact matches the locally generated digest where supported.

## Artifact classes

| Artifact | Workflow | Expected evidence |
| --- | --- | --- |
| Python package `kicad-mcp-pro` | `.github/workflows/publish-python.yml` | wheel/sdist, SHA256 checksums, SBOM, GitHub attestation, registry digest verification, PyPI Integrity API identity plus cryptographic PEP 740 verification |
| npm wrapper `kicad-mcp-pro` | `.github/workflows/publish-npm.yml` | npm tarball, SHA256 checksums, SBOM, provenance, post-publish digest verification |
| Protocol schemas npm package | `.github/workflows/publish-protocol-schemas.yml` | npm tarball, SHA256 checksums, SBOM, provenance, post-publish digest verification |
| Docker image | `.github/workflows/publish-mcp-container.yml` | multi-arch image, labels, SBOM/provenance from buildx, Trivy scan, GHCR digest |
| Tauri GUI installers | `.github/workflows/gui-release.yml` | platform installer bundles attached to the matching GUI release |
| MCP Registry manifest | `.github/workflows/publish-mcp-registry.yml` | manifest validation, package availability verification, registry publish step |

## Required controls

- Workflow default permissions are `contents: read` unless a job needs narrower elevated permissions.
- Jobs that publish, deploy, attest, or mutate release assets declare job-scoped permissions.
- Publish jobs are guarded by repository owner, event type, tag prefix, deployment branch/tag policy, and environment checks.
- Emergency token publishing requires a protected environment approval and an authorization reference.
- Third-party Actions are pinned to full commit SHAs.
- Checkout credentials are not persisted unless a workflow explicitly needs to push.
- Shell steps pass GitHub expressions through `env:` before use in scripts.
- Dependency audit, secret scanning, static analysis, and workflow-security checks are part of the local and CI gates.

## Maintainer checklist

Before approving a release environment:

- [ ] The release tag prefix matches the artifact class.
- [ ] CI and security workflows passed on the release commit.
- [ ] Version metadata is synchronized across `pyproject.toml`, package manifests, `server.json`, and generated docs.
- [ ] The release notes do not overclaim EDA accuracy, sign-off authority, or KiCad coverage.
- [ ] Generated artifacts do not include credentials, private project paths, private board data, or customer files.
- [ ] SBOM, checksum, and attestation steps completed or the exception is documented in the release notes.
- [ ] Post-publish verification completed for PyPI/npm artifacts where supported.

## Incident response

If release integrity is in doubt:

1. Stop the affected publish workflow and revoke any exposed token.
2. Mark affected GitHub Releases, package versions, container tags, or registry entries as compromised or yanked where supported.
3. Open a private GitHub Security Advisory.
4. Cut a patched release through the protected pipeline.
5. Publish a user-facing advisory with affected versions, mitigations, and verification steps.


See also [`release-signing.md`](release-signing.md) for artifact-signing and verification policy.
