# KiCad MCP Pro - one Doppler main config, GitHub CI and Coolify

This is a **prepared, not activated** migration. No secret, domain, GitHub
environment, Coolify application or live deployment was modified.

## Single source of truth

Authoritative Doppler project **kicad-mcp-pro** and only one actively
managed config **main**. Owner updates SonarCloud, Codacy, Cloud, OAuth,
Coolify, publisher and domain values there.

No extra Doppler configs named ci, deploy, release or gui-signing are needed.
Existing prd_cloud, prd, own, live-eval are legacy and must not be
deleted or repointed until source/consumer acceptance is verified.

**Security limit:** Doppler service tokens are config-scoped, not key-scoped.
A main token provides access to ALL production credentials, so it must NEVER
be available in ordinary pull-request CI. Doppler's native GitHub sync copies
every secret in its configured source, which would be unsafe for a combined
main config. Do not connect that bulk sync to this repo. Cross-config
Doppler references also may require a paid plan; none are required here.

Official docs:
- https://docs.doppler.com/docs/service-tokens
- https://docs.doppler.com/docs/github-actions
- https://docs.doppler.com/docs/secrets

| Consumer | Implementation |
| --- | --- |
| SonarCloud/Codacy CI | Existing individually scoped GitHub Actions secrets; source values mirrored from Doppler main by trusted, allowlisted operator sync |
| Live model checks | Existing GitHub provider secrets/environment; mirrored from Doppler main |
| Release App and Tauri GUI signing | Existing protected workflow secret interfaces; mirrored from Doppler main |
| Production deployment | A read-only main service token, *only* in GitHub protected production environment, secret name DOPPLER_TOKEN |
| Coolify Cloud runtime | Existing Doppler integration; switch runtime mappings to main only after proven parity and rollback |

Selected GitHub secret **copies** will still physically exist, even though
all edits originate in Doppler main. A single repo-wide main service token
would reduce the number of copies at the cost of exposing database, signing
and Cloud credentials to PR jobs; this design intentionally avoids that.

## Synchronize selected GitHub secret copies

On a trusted authenticated machine (not GitHub Actions), with Doppler CLI
already logged in and GitHub CLI authenticated as repository owner
oaslananka, run dry-run first (fetches no secret values and writes nothing):

~~~bash
bash scripts/sync_doppler_github.sh quality
~~~

After main has all required nonempty values, copy the selected groups.
Only run groups with verified values:

~~~bash
bash scripts/sync_doppler_github.sh quality --apply
bash scripts/sync_doppler_github.sh live-eval --apply
bash scripts/sync_doppler_github.sh release --apply
bash scripts/sync_doppler_github.sh gui --apply
~~~

The Bash helper runs on a trusted machine (Git Bash works on Windows). It checks
the exact GitHub identity and repo; denies GitHub Actions runners, refuses
arbitrary names or alternative Doppler configs, preflights the selected group
**before any writes**, and pipes each value to GitHub's encrypted secret setter. It prints only the names
and targets, never values. A failed GitHub write may leave a partial sync:
inspect target metadata and retry safely.

The explicitly permitted targets live in the code. Repo-level quality keys
are SONAR_TOKEN, CODACY_PROJECT_TOKEN, CODECOV_TOKEN and SEMGREP_APP_TOKEN.
The optional \`quality-extra\` group mirrors CODECOV_TOKEN and SEMGREP_APP_TOKEN only when populated.\nLive model NVIDIA_API_KEY and OPENCODE_ZEN_API_KEY go to the existing GitHub
environment live-model-evals; OPENAI_KEY currently uses repo-level lookup.
Release GitHub App and GUI signing values use their existing repo-level
workflow secret contracts until a separately reviewed environment migration.

Missing GitHub secret **values cannot be fetched back** through GitHub API.
Import missing originals into Doppler main privately using the provider or
an already authorized source. Never paste keys in chats, Git, PRs, files,
CI logs or Context Ledger. Do not delete existing GitHub secrets until
required checks, live evaluations and protected release workflows pass.

An optional hourly trusted VPS sync can be activated **later**, only after
the manual scoped sync and provider acceptance. No timer, cron job or
background secret-sync service has been installed by this PR. Until then,
the sync is deliberately an explicit command, not instantaneous mirroring.

## One-command protected Cloud deploy

In GitHub Actions create/protect environment **production**, limited to
protected main. Put one manual bootstrap secret there:
DOPPLER_TOKEN = **read-only Doppler service token for kicad-mcp-pro/main**.
NEVER add this main token to repository-level secrets. GitHub's ephemeral
GITHUB_TOKEN and OIDC flows stay as they are.

Populate these key names in Doppler main:

- COOLIFY_URL (existing Coolify HTTPS origin)
- COOLIFY_API_TOKEN (approved current Coolify deploy API credential)
- COOLIFY_APPLICATION_UUID (existing kicad-cloud-api application)
- PUBLIC_ORIGIN (canonical Cloud HTTPS origin)
- OAUTH_ISSUER, OAUTH_JWKS_URL, OAUTH_AUDIENCE

After approved PR merge, green protected main checks, and production
configuration acceptance:

~~~bash
pnpm deploy
~~~

The local command dispatches Cloud Deploy (Coolify) on protected GitHub main
and watches it. It never reads a production token locally. The hosted job
verifies exact-main CI, Cloud CI when Cloud sources changed, the Coolify
repo/branch/Compose target, then performs the deploy and checks deployed
SHA plus public /health revision. Runtime SOURCE_COMMIT is mapped to
APP_REVISION by the Compose file. It does not recreate databases or Tunnel.

The **first** managed rollout requires an existing healthy known revision
and a reviewed rollback route; when not present, it deliberately stops.
Automatic rollback remains disabled until disposable verified acceptance.

## Coolify configuration and domain change

Existing Coolify kicad-cloud-api uses production values that have not all
been proven to originate in Doppler main. After verifying complete parity,
switch only its required runtime variables to main, keeping build-time
secrets restricted. Keep existing live prd_cloud and duplicated variables
until the migrated runtime, OAuth, DB, Tunnel, source revision and rollback
are verified. This script does not carry out that live cutover.

Changing PUBLIC_ORIGIN alone cannot update external Cloudflare DNS, Tunnel
host mappings, Coolify proxy routes, OAuth callback registrations and AI
client metadata. Those need separate provider synchronization and rollback
acceptance before claiming automatic domain migration.

## Acceptance contract

- Only kicad-mcp-pro/main managed as canonical config.
- No all-access main token in ordinary PR/CI; protected deployment only.
- Allowlisted sync for existing GitHub secret consumers, with verified source
  and no secret values logged or stored in source.
- Existing Sonar/Codacy/CodeQL, release and GUI required check contexts
  unchanged and passing on exact head.
- Existing private network/DB/Tunnel preserved; protected deployment
  verifies source SHA, healthy revision and rollback.
- No claims of production activation based only on local unit tests.
