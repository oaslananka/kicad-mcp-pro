# KiCad PCM submission

**Status: not submitted.**

The official KiCad addon metadata repository is:

`https://gitlab.com/kicad/addons/metadata`

KiCad's current repository workflow requires a package archive to exist at a
direct-download location before repository metadata is submitted. The metadata
inside the ZIP has one version and intentionally omits repository-only download
fields; the repository copy then adds `download_url`, `download_sha256`,
`download_size`, and `install_size` for the published artifact.

## Preconditions

Do not submit until all of these are true:

1. #731's physical KiCad install/connect/update/uninstall/rollback evidence is complete.
2. A tagged `mcp-server-v<version>` release contains the deterministic
   `kicad-mcp-pro-pcm-<version>.zip` produced by `publish-kicad-pcm.yml`.
3. The release checksum and GitHub attestation have been verified.
4. The public package identifier remains unique and exactly
   `com.github.oaslananka.kicad-mcp-pro`.
5. The package still declares its actual runtime (`swig`) and supported KiCad
   minimum rather than an aspirational modern-IPC state.

## Repository submission procedure

1. Fork/update the official metadata repository and create a feature branch.
2. Create `packages/com.github.oaslananka.kicad-mcp-pro/`.
3. Start from this repository's generated internal metadata for the exact release.
4. Add the direct GitHub Release `download_url` plus the exact
   `download_sha256`, `download_size`, and `install_size` from release evidence.
5. Add the approved 64x64 icon using the official repository layout.
6. Run the metadata repository's Packaging Toolkit/validation locally.
7. Push the branch and require the fork pipeline's validation/build jobs to pass.
8. Use the temporary PCM repository emitted by that pipeline to install and test
   the package in KiCad again.
9. Only then open the merge request to the KiCad addon metadata project.
10. After upstream review/merge, verify the package appears in the public PCM
    repository before changing this project's readiness matrix to an official
    listing.

The submission metadata is deliberately **not** generated into the source tree
with placeholder download URLs. Final download fields are release-derived facts
and must come from the published, digest-verified artifact.
