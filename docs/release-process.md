# Release Process

Releases use Conventional Commits and release-please as the canonical release PR
and changelog mechanism. Release Drafter is not used.

The release-please workflow uses the repository-scoped `GITHUB_TOKEN` with the
least-privilege permissions declared in `.github/workflows/release-please.yml`.
No long-lived release token is required.

## Normal Release

1. Confirm CI, Security, CodeQL, docs, and release checks are green.
2. Merge the release-please PR.
3. Confirm `.github/workflows/release-please.yml` created the release tag and
   GitHub Release from release-please outputs.
4. Approve the protected `release` environment gate for the publish job.
5. Confirm PyPI publish, SBOM, checksums, Sigstore signing artifacts,
   and GitHub attestations.
6. Confirm docs deploy to the canonical repository `gh-pages` branch and
   `https://oaslananka.github.io/kicad-mcp-pro/` Pages site.
7. Post a short GitHub Discussions announcement.

## Release Workflow

The release workflow has no operator-supplied version fields. Release-please
derives the version from Conventional Commits and `.release-please-manifest.json`.
When release-please reports that a release was created, the publish job checks
out the release tag, runs the full verification gate, builds artifacts,
generates SBOM and checksum files, creates provenance attestations, signs
artifacts, publishes to PyPI through trusted publishing, verifies the package
with a clean `uv` environment, and attaches release assets to the GitHub Release.

Publishing must not be triggered from pull requests, forks, local shells, or
manual tag creation.

## Hotfix

Use `hotfix/<issue>` for urgent security, data loss, or production blocking fixes. Cherry-pick to a maintained release branch only when that branch exists and has users.

## Version Metadata

Run this before release PR review if metadata changes are manual:

```bash
pnpm run metadata:sync
pnpm run metadata:check
```

`pyproject.toml` is the source of truth for `server.json`.
