# Renovate migration pilot — parked, not activated (24 October 2026)

## Ownership and safety

- Dependabot remains active for version and security update PRs. Its existing
  .github/dependabot.yml and Mergify safe-dependencies queue are unchanged.
- renovate.json has enabled=false. No Renovate dependency PR, dashboard or
  lockfile update should be produced in this parked state. A separate, reviewed
  change is needed to activate the pilot; installing a GitHub App requires
  the account owner's action.
- GitHub dependency graph and Dependabot Alerts remain enabled.
- Renovate automerge and platformAutomerge are disabled. Mergify is the
  only merge authority.

## Prototype rules

The Renovate pep621 manager supports pyproject.toml and uv.lock (it is NOT
called uv). Other managers cover npm, GitHub Actions, Dockerfile,
Docker Compose, and Cargo. The proposed policy limits concurrent PRs to two,
new PRs to one per hour and ordinary release age to five days.
GitHub vulnerability-alert remediation does not inherit the ordinary wait.
Lockfile maintenance is separately disabled pending review of its release-age exception; the schedule is documented but not active.
Minor and patch updates are kept separate. Major upgrades require manual Dependency Dashboard approval.

The new Mergify renovate-pilot-safe queue requires every existing
safe-dependencies CI check plus a real renovate[bot] author, renovate/ branch,
renovate-patch label, and separately OPERATOR-APPLIED
renovate-pilot-approved label. The label is never automatically applied by
the bot. No review bypass or CI bypass is allowed.

## Separate, explicitly authorized activation sequence

1. Resolve or triage the 15 currently open Dependabot alerts: 3 high pypdf,
   4 medium fastmcp/fastmcp-slim and 8 fast-uri (4 medium, 4 low).
   PR #1445 prepares the pypdf security fix.
2. Validate configuration with renovate-config-validator --strict, GitHub
   PR CI and Mergify checks. Keep Renovate disabled at this stage.
3. If desired, the owner installs Renovate's hosted GitHub App with the
   minimum necessary repository permissions. Connecting the app is a
   distinct user-authorization step.
4. In a distinct reviewed activation PR, switch Renovate on for a narrow
   subset while retiring ONLY overlapping Dependabot version update
   sources, preserving GitHub vulnerability alerts and branch protection.
5. Pilot one patch update, review actual lockfile differences, apply the
   manual approval label, verify Mergify protected queue and check that
   Dependabot did not raise a duplicate PR.
6. Compare PR volume, CI failures, time to merge and manual interventions
   with the Dependabot baseline before considering wider rollout.

Rollback: remove the approval label, restore Renovate enabled=false in a
protected PR, leave Dependabot and GitHub Alerts active, and inspect
in-flight Renovate PRs. Disabling Renovate can clean up its own PRs/branches;
do not toggle it casually during ongoing reviews.

This pilot does not modify KiCad MCP #1179 immutable-Release gates or any
existing production release workflow.
