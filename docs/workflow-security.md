# Workflow Security

## Required Posture

- Default workflow permissions are `contents: read`.
- Jobs that publish, release, deploy, attest, or mutate issues/labels use
  job-scoped permissions and explicit repository or environment guards.
- Normal CI, lint, test, docs, CodeQL, Gitleaks, Trivy, and workflow-security
  checks run on pull requests and canonical pushes.
  Publishing, release, registry, package-manager, signing, and deploy
  jobs keep `github.repository == 'oaslananka/kicad-mcp-pro'` guards.
- Third-party Actions are pinned to full commit SHAs resolved from upstream refs.
  Do not replace these with fabricated SHAs.
- JavaScript Actions should declare `runs.using: node24` when an upstream
  Node 24 release exists. Do not rely on `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`
  as a permanent fix for deprecation annotations.
- Shell steps must pass GitHub expression values through `env:` before using
  them in scripts.

## Local Checks

```bash
corepack pnpm run workflows:lint
corepack pnpm run workflows:security
```

`workflows:lint` parses workflow YAML and runs actionlint with ShellCheck. `workflows:security`
runs zizmor offline at high severity or above. Medium findings such as checkout
credential persistence are still reviewed, but high findings block the local and
CI gate.

Trivy image scans use `ignore-unfixed: true`, matching the local
`task security:local` policy. HIGH/CRITICAL vulnerabilities with available fixes
still fail the gate; base-image advisories with no patched package stay visible
in SARIF without blocking every PR.

## Pinning Updates

When updating a pinned Action, resolve the new ref directly from GitHub, for
example:

```bash
git ls-remote --tags https://github.com/actions/checkout.git 'refs/tags/v6^{}'
```

If a tag cannot be resolved, do not guess. Leave the old pin in place or document
the exact unresolved action and stop the change.

After updating a pin, inspect the resolved `action.yml` or `action.yaml` and
confirm JavaScript actions no longer declare a deprecated Node runtime.

## Deterministic local tooling

`actionlint-py` and `shellcheck-py` are exact-version development dependencies,
so `uv sync --all-extras --frozen` supplies the same workflow parser and shell
analyzer on Linux, macOS, and Windows. `scripts/check_workflows.py` invokes the
real `actionlint` binary directly; a missing or failing binary is an error rather
than a successful no-op. Zizmor remains locked in `uv.lock` and runs offline.

## Node 24 runtime audit

Direct JavaScript Actions use Node 24-capable releases. In particular, the
path filter is pinned to `dorny/paths-filter` v4.0.1 and artifact uploads use
`actions/upload-artifact` v7.0.1. When changing an Action pin, inspect the
pinned commit's `action.yml` rather than assuming a major tag's runtime.

## Coverage reporting services

The `CI Tests / Coverage` job uploads the same `coverage.xml` (Cobertura
format produced by `pytest-cov`) to two services:

- **Codecov** — primary coverage and test-analytics service. Uses OIDC on
  canonical pushes and a token on fork PRs.
- **Codacy** — quality dashboard; receives the identical `coverage.xml` as a
  secondary signal. Upload uses the official `get.sh` shell reporter
  (`https://coverage.codacy.com/get.sh`) with `CODACY_REPORTER_VERSION`
  pinned to a specific stable release (currently `14.1.3`, verified from the
  upstream GitHub Releases API). The reporter performs SHA512 checksum
  verification automatically for versions ≥ 13; `CODACY_REPORTER_SKIP_CHECKSUM`
  is **not** set. Authentication is via the repository-scoped GitHub Actions
  secret `CODACY_PROJECT_TOKEN` (set in _Settings → Secrets and variables →
  Actions_).

Both Codacy and Codecov uploads run with `continue-on-error: true`. The
`Propagate Python coverage or test failure` step only checks
`steps.python-tests.outcome` and `steps.patch-coverage.outcome`, so a
transient Codacy upload failure cannot break the 83 % overall or 90 % patch
coverage gates. If `CODACY_PROJECT_TOKEN` is absent, the step prints a
`::warning::` annotation and exits 0 rather than failing silently.

Tests are never run twice: the Codacy step only uploads the artifact that the
main test step already produced.

To update the pinned reporter version, resolve the new tag from the upstream
releases API and update `CODACY_REPORTER_VERSION` in the workflow env block:

```bash
curl -s https://api.github.com/repos/codacy/codacy-coverage-reporter/releases/latest \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])"
```
