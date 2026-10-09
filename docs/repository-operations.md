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

`.github/workflows/release-please.yml` runs daily at 03:37 UTC or on
maintainer dispatch to **prepare or update the protected release PR**.
It derives package versions from Conventional Commits and synchronizes
generated release metadata. It does not create tags or publish releases.

After reviewing and merging the release PR, the maintainer explicitly runs
**Actions → Publish Release → Run workflow** on `main`. That workflow alone
normally creates GitHub Release tags and records. Tag/release events then
start the artifact-specific publish workflows under their existing security
and provenance gates. See [development release process](development/release-process.md)
and [release checklist](release-process.md) for the exact sequence.

Both release-preparation and publication workflows mint short-lived GitHub
App installation tokens, not a maintainer PAT. Python package publishing
uses the `publish-python.yml` workflow with PyPI/TestPyPI OIDC trusted
publishing, package checksums and verified publication attestations.
The `pypi` and `testpypi` environments belong to those publish jobs.

Manual version inputs, manual tag creation, direct local publishing and
hand-edited changelog entries are not part of the normal release process.
Recovery workflow dispatches are not alternate normal publication entry points.

## Maintenance Workflows

Dependabot handles scheduled updates under `.github/dependabot.yml`; guarded
Mergify queues are configured in `.mergify.yml`. The repository-settings
audit runs from `.github/workflows/repository-settings-audit.yml`. Check
current Actions runs and the branch ruleset when diagnosing failures; do not
assume an old or renamed maintenance workflow still exists.

References:

- [CI/CD policy](engineering/ci-cd-policy.md)
- [GitHub Actions security policy](security/github-actions-policy.md)

## Branch Hygiene

Generate a read-only report of stale branches and old open PRs with the
maintained `scripts/branch_hygiene_report.py` script:

```bash
python3 scripts/branch_hygiene_report.py --repo oaslananka/kicad-mcp-pro --days 90
```

The script does not delete branches, issues or PRs. Review branch ownership,
open PRs, active worktrees and release/tag protection before any separately
authorized cleanup; no automatic stale-branch deletion is configured here.

The canonical GitHub repository already has
`delete_branch_on_merge: true`, which deletes eligible merged PR branches.
This is separate from deleting old or abandoned branches.
