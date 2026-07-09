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

`workflows:lint` parses workflow YAML and runs actionlint. `workflows:security`
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
