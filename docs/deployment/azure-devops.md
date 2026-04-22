# Azure DevOps Manual CI/CD

Azure DevOps is a manual fallback and release-support surface for this repository. Automated GitHub CI/CD is owned by the `oaslananka-lab` organization mirror, while the personal `oaslananka` GitHub repository remains the main source repository.

## Pipeline Definition

The primary Azure pipeline definition lives in the repository root as `azure-pipelines.yml`.

It covers:

- `Validate`: `uv sync`, `ruff`, `mypy`, and `pytest` with a `--cov-fail-under=70` gate
- `Build`: `uv build` and artifact publication for the generated `dist/` output
- `Publish`: optional manual release to TestPyPI or PyPI using Azure-managed secrets

## Recommended Azure Variables

Preferred setup: store a single Doppler service token in Azure DevOps and let the pipeline fetch release secrets at runtime:

- `DOPPLER_TOKEN`

Doppler should contain:

- `PYPI_TOKEN`
- `TEST_PYPI_TOKEN`
- `SAFETY_API_KEY`

The root `azure-pipelines.yml` still supports native Azure variables as a fallback:

- `PYPI_TOKEN`
- `TEST_PYPI_TOKEN`
- `SAFETY_API_KEY`

You can store these in a variable group if you want to share them across multiple pipelines.

## Release Model

- Automated GitHub CI/security jobs should run from `https://github.com/oaslananka-lab/kicad-mcp-pro`.
- Azure DevOps should be queued manually when you need the Azure validation or release-support path.
- Package publication should always be queued manually when you are ready to release.
- The personal GitHub repository should not run automatic CI/CD jobs.

## GitHub Workflows

The repository includes GitHub workflows that are automatic only in the `oaslananka-lab` organization mirror and manual elsewhere:

- `.github/workflows/ci.yml`
- `.github/workflows/security.yml`
- `.github/workflows/publish.yml`

`ci.yml` and `security.yml` run on `push` and `pull_request` only when `github.repository_owner == 'oaslananka-lab'`. `publish.yml` remains manual because package publication should require a human release decision.
