# Release Process

Releases use Conventional Commits and release-please as the canonical release PR
and changelog mechanism. Release Drafter is not used.

The release-please workflow uses `DOPPLER_GITHUB_SERVICE_TOKEN` when it is
available, with `GITHUB_TOKEN` as a fallback. This keeps the repository default
workflow permission at read-only while still allowing release-please to open
release PRs in organizations that block `GITHUB_TOKEN` pull-request creation.

## Normal Release

1. Confirm CI, Security, CodeQL, docs, and release checks are green.
2. Merge the release-please PR.
3. Confirm the tag and GitHub Release were created.
4. Run the manual `Release` workflow from the protected release repository.
5. Approve the `release` environment gate.
6. Confirm PyPI/TestPyPI publish, SBOM, checksums, Sigstore signing artifacts, and GitHub attestations.
7. Confirm docs deploy to the repository `gh-pages` branch and mirror to the canonical `https://oaslananka.github.io/kicad-mcp-pro/` Pages site.
8. Post a short GitHub Discussions announcement.

## Manual Release Workflow

Run `.github/workflows/release.yml` from `oaslananka-lab/kicad-mcp-pro`.

Inputs:

- `version`: release tag, for example `v3.0.3`.
- `index`: `TestPyPI` or `PyPI`.
- `publish`: set to `true` only for actual registry publication.
- `approval`: set to `APPROVE_RELEASE` when `publish=true`.

The workflow verifies the required GitHub Actions publish token for the selected
index, runs tests and security checks, builds artifacts, creates SBOM output,
attests artifacts, and publishes through `scripts/publish.sh` only when
`publish=true` and the protected environment is approved. Doppler remains the
preferred source for syncing secret names into GitHub, but the release workflow
does not block on unrelated Doppler entries such as Codecov or Safety.

There is no separate publish workflow. Publishing must not be triggered from
pull requests, forks, local shells, or agent automation.

## Hotfix

Use `hotfix/<issue>` for urgent security, data loss, or production blocking fixes. Cherry-pick to a maintained release branch only when that branch exists and has users.

## Version Metadata

Run this before release PR review if metadata changes are manual:

```bash
npm run metadata:sync
npm run metadata:check
```

`pyproject.toml` is the source of truth for `mcp.json` and `server.json`.
