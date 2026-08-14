# Sonar Fork PR Secret Safety Design

## Problem

The SonarCloud workflow runs on `pull_request` events and injects `secrets.SONAR_TOKEN` into the scanner step. GitHub intentionally withholds repository secrets from pull requests whose head repository is a fork, so those scans start without `SONAR_TOKEN` and fail with authorization errors.

## Design

Keep the existing `pull_request` trigger and `push` trigger. Do not switch to `pull_request_target`, because running fork-controlled code in a secret-bearing job would expand the trust boundary.

Gate the SonarCloud job so it runs only when:
- the repository owner is one of the existing allowed owners; and
- the event is not a pull request, or the pull request head repository is the same repository as the base repository.

This preserves Sonar analysis for `main` pushes and same-repository pull requests while safely skipping fork pull requests that cannot receive the secret.

## Verification

Add a workflow regression test that parses `.github/workflows/sonarcloud.yml` and asserts the job condition includes the same-repository head check. Run the targeted workflow tests, GitHub Actions policy tests, Ruff, workflow checker, and YAML parsing before pushing.
