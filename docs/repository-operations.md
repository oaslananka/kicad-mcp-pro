# Repository Operations

## Repositories

- Canonical source-of-truth: `oaslananka/kicad-mcp-pro`

The canonical repository is the only source repository for CI/CD, release,
publishing, registry updates, package-manager updates, signing, SBOM generation,
and artifact attestations.

## Actions Policy

Keep Actions enabled anywhere branch protection depends on them. Use least
privilege workflow permissions and protected environments rather than disabling
normal validation.

## Release Automation

Release automation is driven by `.github/workflows/release-please.yml` on
merges to `main`. Release-please opens the release pull request, derives the
SemVer version from Conventional Commits, creates the GitHub Release after the
release pull request is merged, and exposes the release version and tag to the
publish job.

Manual version inputs, manual tag creation, and hand-edited changelog entries
are not part of the release process.

## Maintenance Workflows

`.github/workflows/actions-maintenance.yml` can list and classify failed runs,
reports stale deployments/tags, and can rerun infra-only failures when
explicitly requested. It does not create releases, packages, tags, or force
pushes.

References:

- [Failure classifier](automation/failure-classifier.md)
- [Review thread gate](automation/review-thread-gate.md)

## Pending: OIDC Trusted Publishing

The current release pipeline publishes with `pypa/gh-action-pypi-publish` and
GitHub Actions OIDC. Long-lived package-index tokens are not required by
`.github/workflows/release-please.yml`.

Migration path:

1. Configure a trusted publisher in the PyPI project settings pointing to
   `oaslananka/kicad-mcp-pro`, workflow `release-please.yml`, environment `release`.
2. Configure the matching trusted publisher in TestPyPI with the same owner,
   repository, workflow, and environment.
3. Keep `id-token: write` on the release publish job so PyPI can mint short-lived
   publish credentials during the protected `release` environment run.
4. Remove any remaining package-index token secrets from the org repo after the
   PyPI trusted publisher is confirmed.

Blocked by: requires PyPI and TestPyPI account owner action to configure the
trusted publishers.

## Branch Cleanup

Review planned cleanup actions:

```bash
bash scripts/repo-cleanup.sh
```

Apply after reviewing the dry run:

```bash
bash scripts/repo-cleanup.sh --apply
```

The monthly `Branch hygiene report` workflow is report-only. It writes a job
summary and does not create issues or delete branches.

## Auto-Delete Merged PR Branches

Recommended one-time setting on the canonical repository:

```bash
gh api -X PATCH /repos/oaslananka/kicad-mcp-pro -f delete_branch_on_merge=true
```
