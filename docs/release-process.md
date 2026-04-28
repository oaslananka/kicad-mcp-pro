# Release Process

Releases use Conventional Commits and release-please as the canonical release PR mechanism.

## Normal Release

1. Confirm CI, Security, CodeQL, docs, and release checks are green.
2. Merge the release-please PR.
3. Confirm the tag and GitHub Release were created.
4. Run the manual `Release` workflow from the `oaslananka-lab` mirror.
5. Approve the `release` environment gate.
6. Confirm PyPI/TestPyPI publish, SBOM, checksums, Sigstore signing artifacts, and GitHub attestations.
7. Confirm docs deploy to `gh-pages`.
8. Post a short GitHub Discussions announcement.

## Manual Release Workflow

Run `.github/workflows/release.yml` from `oaslananka-lab/kicad-mcp-pro`.

Inputs:

- `version`: release tag, for example `v3.0.3`.
- `index`: `TestPyPI` or `PyPI`.
- `publish`: set to `true` only for actual registry publication.
- `approval`: set to `APPROVE_RELEASE` when `publish=true`.

The workflow verifies Doppler secrets, runs tests, builds artifacts, creates SBOM output, attests artifacts, and publishes through `scripts/publish.sh`.

## Hotfix

Use `hotfix/<issue>` for urgent security, data loss, or production blocking fixes. Cherry-pick to a maintained release branch only when that branch exists and has users.

## Version Metadata

Run this before release PR review if metadata changes are manual:

```bash
npm run metadata:sync
npm run metadata:check
```

`pyproject.toml` is the source of truth for `mcp.json` and `server.json`.
