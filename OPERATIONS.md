# Operations: Required Human Actions

This file documents tasks that cannot be performed by an automated agent and require a
human operator with the appropriate permissions.

## PyPI Trusted Publishing Setup

Status: not yet configured as of May 2026. The package is published through twine.

Required steps:

1. Go to https://pypi.org/manage/project/kicad-mcp-pro/settings/
2. Navigate to Publishing, then add a new publisher.
3. Select GitHub Actions.
4. Set owner to `oaslananka`, repository to `kicad-mcp-pro`, workflow name to
   `release.yml`, and environment to `release`.
5. Remove token-based PyPI secrets after Trusted Publishing is active.
6. Update `.github/workflows/release.yml` to use `pypa/gh-action-pypi-publish` with
   attestations enabled instead of twine.

## GitHub Protected Environment: release

Required steps:

1. Go to https://github.com/oaslananka/kicad-mcp-pro/settings/environments
2. Create an environment named `release`.
3. Add required reviewers, at minimum `@oaslananka`.
4. Enable the required reviewers gate.
5. Set deployment branch protection to `main` only.

## GitHub Protected Environment: docs

Create a `docs` protected environment with required reviewers for documentation deployment.

## Scorecard and Codecov Badges on Canonical Repo

Required steps:

1. Enable GitHub Actions on `oaslananka/kicad-mcp-pro`.
2. If the lab mirror remains the only CI runner, update README badge notes so the target
   repository is explicit and not misleading.

## Doppler Secret Rotation

When rotating secrets:

1. Update Doppler project `all`, config `main`.
2. Re-run the sync workflow in `oaslananka-lab/kicad-mcp-pro`.
3. Verify no hardcoded secrets remain with `git log --all --full-history -- .env*`.

## KiCad 10 Test Runner Access

For the nightly KiCad 9/10 matrix:

1. A runner with KiCad 10.0.x installed must be available.
2. Set `KICAD_CLI_PATH` in the runner environment.
3. Label the runner `kicad-10` in GitHub Actions.
