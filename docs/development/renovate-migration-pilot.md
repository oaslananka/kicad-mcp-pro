# Renovate migration pilot — staged activation (27 October 2026)

## Ownership and safety

- On production main, Dependabot remains active for version and security
  updates and Renovate is disabled. The draft activation PR changes only one
  npm path while retiring its counterpart Dependabot version producer.
- Hosted App installation needs GitHub account-owner approval. Never presume
  its presence from a previous Renovate PR alone.
- GitHub dependency graph and Dependabot Alerts remain enabled.
- Renovate automerge and platformAutomerge are disabled. Mergify is the
  only merge authority.

## Staged single-directory activation (27 October 2026)

This draft activation change enables Renovate for only the
integrations/chatgpt-app/apps-sdk npm package and its own package-lock.json,
paired with removal of the matching Dependabot version-update directory.
Other npm, Python, Rust, Actions and container update producers are preserved.
Renovate vulnerability-fix PR creation stays off for the pilot to avoid
a second security PR producer. GitHub Dependabot Alerts and automated
security updates remain independently enabled.

Do not merge this activation PR until the account owner verifies the
Mend-hosted Renovate GitHub App is installed for exactly this repository.
Draft state is a safety interlock, not proof of live bot integration.
The main-branch enabled=false policy remains effective until protected merge.

Validated on 27 October 2026 with Renovate 44.188.2:
- Repo configuration: strict validator PASS (--strict --no-global).
- Local read-only --platform=local --dry-run=extract: npm only, exactly one
  package.json with 14 dependencies.
- Local --dry-run=lookup: PASS, with patch candidates including hono and
  ip-address (and major/minor candidates excluded from automatic approval).
  Five-day minimum release age still applies at PR proposal time.
- In-repo pytest tests: 32 relevant policy and release-preflight tests passed
  under the pinned Python/uv toolchain.
- The actual GitHub Dependabot Alerts API returned zero open alerts;
  separate code-scanning Rust advisories remain tracked by #1450.
- Existing GitHub-hosted bot status and deployment are not established by
  local dry-run; install only via https://github.com/apps/renovate and select
  only oaslananka/kicad-mcp-pro. Review requested permissions in GitHub.

Pre-activation checklist:
- Owner verifies App installation limited to oaslananka/kicad-mcp-pro.
- Strict Renovate repo-config validation and local dry-run extract/lookup
  show exactly the selected npm package. No actual PRs are created during
  dry-run and no credentials are committed.
- Verify GitHub Dependabot Alerts, automated security updates and independent
  code scanning; existing Rust advisories remain tracked by #1450.
- Preserve Mergify manual renovate-pilot-approved label, real Renovate bot
  identity, protected checks, zero bot automerge and one concurrent pilot PR.
- After protected activation, inspect the bot Dependency Dashboard, accept
  exactly one low-risk patch candidate, verify zero Dependabot duplicates,
  and compare CI failures, time to merge and manual maintenance.
- Keep #1449 open until live bot installation and patch PR acceptance pass.

Rollback: restore enabled=false and the removed Dependabot version-update
directory in a protected PR. Keep GitHub Alerts and security updates active.
No release workflows or immutable GitHub Releases settings are changed.

## Prototype rules

The Renovate pep621 manager supports pyproject.toml and uv.lock (it is NOT
called uv). Other managers cover npm, GitHub Actions, Dockerfile,
Docker Compose, and Cargo. The staged pilot limits concurrent PRs to one,
new PRs to one per hour and ordinary release age to five days.
Renovate vulnerability-alert PR generation is deliberately disabled for this narrow npm pilot;
Dependabot automated security updates stay on. Normal five-day release age still applies
to routine updates. Lockfile maintenance is separately disabled pending review of its release-age exception; the schedule is documented but not active.
Minor and patch updates are kept separate. Major upgrades require manual Dependency Dashboard approval.

The new Mergify renovate-pilot-safe queue requires every existing
safe-dependencies CI check plus a real renovate[bot] author, renovate/ branch,
renovate-patch label, and separately OPERATOR-APPLIED
renovate-pilot-approved label. The label is never automatically applied by
the bot. No review bypass or CI bypass is allowed.

## Dependency security checkpoint (26 October 2026)

- A read-only GitHub Dependabot Alerts API query for **open** alerts returned
  **0** on 26 October 2026. The previous **15** open pypdf, fastmcp/fastmcp-slim
  and fast-uri alert records were a 24 October snapshot, **not** the current
  queue; reviewed package updates were merged separately. Do not dismiss,
  downgrade or suppress future alerts to keep this count at zero.
- A separate read-only **Code Scanning** API query still returned **6 open**
  OSV/RustSec entries representing **5 distinct Rust dependency issues**
  (the glib unsoundness has two alias records). Track these under #1450;
  zero Dependabot alerts must **not** be described as a clean Rust or full
  repository vulnerability scan.
- This is a **dated observation**, not a persisted health guarantee. Re-query
  both alert channels and verify the default-branch dependency snapshot
  immediately before any future Renovate activation decision. The
  Dependabot vulnerability-alert channel stays enabled throughout.

## Separate, explicitly authorized activation sequence

1. Reconfirm live Dependabot Alerts and Code Scanning findings against the
   default-branch dependency graph; triage any newly open security warnings
   independently. Preserve Dependabot Alerts even if version-update sources
   are later switched.
2. Validate the draft as repository config with renovate-config-validator --strict --no-global,
   GitHub PR CI and Mergify checks. Keep Renovate disabled on main at this stage.
3. If desired, the owner installs Renovate's hosted GitHub App with the
   minimum necessary repository permissions. Connecting the app is a
   distinct user-authorization step.
4. Merge the distinct reviewed activation PR only after App installation has been
   independently verified; it switches Renovate on for the single npm path and
   retires only the matching Dependabot version-update source, preserving
   GitHub security alerts, security fixes and branch protection.
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
