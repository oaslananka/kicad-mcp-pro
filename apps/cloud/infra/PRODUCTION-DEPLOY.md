# Production deployment: CI-gated, VPS-executed, audited in Actions

## Existing Cloud origin — unified repository handoff

The owner-approved existing production host now runs the unified app from
`oaslananka/kicad-mcp-pro`, with the Cloud application in `apps/cloud`.
The previous standalone Cloud release timer must stay **disabled** while this
source integration is still a draft PR. Do not deploy an unmerged PR through
the release timer or enable the old repository's watcher.

After exact-head source integration is accepted and merged into `main`,
prepare a clean, dedicated worktree of **this repository** at the reviewed
remote-main SHA. Run the release-watcher installer from `apps/cloud`,
using the existing VPS, existing Doppler settings, existing private ingress
network and the original production hostname. The installer requires the
explicit cutover confirmation, rejects active legacy timers, and refuses
unmerged or stale checkouts. Main releases require a successful exact-SHA
`cloud-ci.yml` push run before application-only deployment.

The owner-approved production database, OAuth provider registrations and
Cloudflare Tunnel are reused. This handoff is not permission to install a
second public endpoint or to apply outstanding SQL migrations.


This file describes the **existing** VPS's current legacy network and production
rollout. For a fresh VPS/domain, use [PORTABLE-DEPLOY.md](PORTABLE-DEPLOY.md).
Current app/Tunnel source and GitHub workflow preserve existing behavior.
Public acceptance now resolves `PUBLIC_ORIGIN` via the GitHub's single
production-scoped `DOPPLER_TOKEN`, while the VPS release timer reads the same
configured destination through Doppler. Existing legacy Doppler selectors
remain default unless a VPS-scoped service token is explicitly configured.


No staging environment. Docker Compose retains one active KiCad image
(`kicad-mcp-pro-cloud:production`), one previous rollback image
(`kicad-mcp-pro-cloud:rollback`), and the PostgreSQL 17 service. There is
no external runner, public deployment port or SSH permission from Actions.

## Automatic application-only release flow

1. GitHub Actions `CI` runs on every push to `main` (typecheck, unit and
   PostgreSQL tests, security/infra gates and OCI build).
2. After the exact `main` CI succeeds, GitHub Actions `Production Deployment`
   starts. It refuses PR, fork, failed CI, and superseded main revisions.
3. On the existing VPS, a `systemd --user` timer checks current `main` every
   two minutes. Only when it differs from the running revision, it fetches
   public CI run metadata and requires a successful **push/main** `CI` for
   that exact SHA. It builds and deploys that commit, without a secret on
   GitHub Actions or an inbound deploy webhook.
4. The VPS deployer saves the previous application image as the one rollback,
   recreates **only** the app, checks Docker health and the production smoke
   including the exact SHA. On failure it recreates the previous app.
5. GitHub Actions waits for `/health` to report the expected revision, then
   runs a separate public smoke and **real Chromium form POST** (must redirect
   to `github.com`, with no user authorization performed). Deployment is green
   only when live acceptance passes. Failure remains visible in Actions.

The source of truth for the running revision is `GET /health` → `revision`.
The `APP_REVISION` build argument contains only a public Git commit SHA.
Production app, database and Cloudflare are not recreated for CI tests.
Migrations are a **separate explicit process**, never a hidden deploy hook.

### One-time VPS timer setup

Keep the regular development checkout and create one clean dedicated deployment
worktree, for example:

    git worktree add --detach "$HOME/Desktop/OPS_WORKSPACE/GITHUB/oaslananka/.worktrees/kicad-mcp-pro-cloud-production" origin/main
    cd "$HOME/Desktop/OPS_WORKSPACE/GITHUB/oaslananka/.worktrees/kicad-mcp-pro-cloud-production"
    bash scripts/install-production-deploy-timer.sh
    systemctl --user status kicad-cloud-production.timer

The user systemd manager must have linger enabled, Docker group access and
existing Doppler login. `scripts/install-production-deploy-timer.sh` creates
only a KiCad-specific user service/timer using this verified checkout; it
adds no deploy tokens or network listeners. Use
`systemctl --user start kicad-cloud-production.service` to trigger a check,
`journalctl --user -u kicad-cloud-production.service` to inspect results, and
`systemctl --user disable --now kicad-cloud-production.timer` to pause it.
Do not edit the deployment worktree while the timer is running.

### Configuration ownership

| Surface | Values | Responsibility |
| --- | --- | --- |
| Doppler `kicad-mcp-pro / prd_cloud` | `PUBLIC_ORIGIN`, `OAUTH_ISSUER`, `OAUTH_JWKS_URL`, `OAUTH_AUDIENCE`, `KICAD_DB_PASSWORD`, `AUTH_MODE`, `BETTER_AUTH_SECRET`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | Existing VPS runtime; never commit values |
| Docker Compose `infra/compose.production.yml` | App/DB volumes, healthcheck, private networks, image tag | Existing VPS |
| GitHub Actions `CI` | Main/PR checks; no production credentials | GitHub hosted |
| GitHub Actions `Production Deployment` | Exact CI SHA, environment `production`, public `/health` and browser acceptance | GitHub hosted, no SSH/Doppler token |
| VPS user timer + deploy script | Outbound-only polling, local Docker build, rollback and Doppler inject | Existing VPS |
| Cloudflare Tunnel | Existing HTTPS public host mapping, no new tunnel | Unchanged |

The only existing GitHub repository secret remains `DOPPLER_TOKEN` for a
separately manually triggered configuration check. Automatic deployment does
not use this token or require additional GitHub secrets.


The database network is internal with no published port. The application
joins that network plus the preexisting ops_internal Cloudflare tunnel
network. Other services and domains are untouched.

All persistent secrets are in Doppler project kicad-mcp-pro / config prd_cloud.
Required variables: KICAD_DB_PASSWORD, PUBLIC_ORIGIN,
OAUTH_ISSUER, OAUTH_JWKS_URL and OAUTH_AUDIENCE. DATABASE_URL contains no credentials; pg uses PGPASSWORD from the Doppler password.
GitHub Secrets must contain only DOPPLER_TOKEN.

The default is AUTH_MODE=external; the current live deployment explicitly uses
AUTH_MODE=builtin from Doppler for GitHub-only login. After registering and securely
storing a real GitHub OAuth Web app in the existing Doppler config,
AUTH_MODE=builtin may be explicitly set for first-login acceptance.
Google credentials are optional until the second provider is registered;
a partial provider pair aborts startup. Real GitHub sign-in and
ChatGPT/Claude OAuth callbacks have not yet completed acceptance. A
working premium page or /health does not imply that the device connector
or remote KiCad execution is operational.

## Reviewed VPS runbook

From the checked-out repository root:

1. For manual recovery only, build with the reviewed commit:
   docker build --build-arg APP_REVISION="$(git rev-parse HEAD)" -t kicad-mcp-pro-cloud:production .
2. Inject Doppler config into Docker Compose invocation:
   doppler run -p kicad-mcp-pro -c prd_cloud -- docker compose -f infra/compose.production.yml up -d db
3. Review SQL and backup. Check pending migrations, then explicitly apply:
   doppler run -p kicad-mcp-pro -c prd_cloud -- docker compose -f infra/compose.production.yml run --rm app node dist/migrations-cli.js --status
   For an approved apply, change --status to --apply.
4. Start application:
   doppler run -p kicad-mcp-pro -c prd_cloud -- docker compose -f infra/compose.production.yml up -d app
5. Set Cloudflare route only for the approved hostname to
   http://kicad-cloud-app-1:8787; retain all other tunnel entries and 404 fallback.
6. Confirm /health, /, /assets/ui.css, OAuth resource metadata, and
   401 authentication_required on an anonymous MCP request. No app or DB
   ports should be publicly published.
7. Remove unused obsolete KiCad app images only. Do not run global image
   prune: this VPS hosts other independent production services.

Migrations do not execute at server startup. Production database backups
remain necessary; an app image rollback does not roll back database migrations.

## Production-only operational checks and database recovery

The following checks create neither staging nor a second application image.

After a release, execute:
    node scripts/production-smoke.mjs

The script verifies HTTPS, the premium page and CSS, honest connector status,
OAuth resource metadata, anonymous MCP denial and disabled signup.

For a private single encrypted database snapshot, execute on the VPS:
    doppler run -p kicad-mcp-pro -c prd_cloud -- bash scripts/production-backup.sh

Production Doppler must contain KICAD_BACKUP_AGE_IDENTITY and its corresponding
KICAD_BACKUP_AGE_RECIPIENT. The script streams a logical pg_dump through
authenticated age encryption, verifies decryption and pg_restore archive
parsing, and atomically replaces one private encrypted snapshot in the
Ubuntu account's home directory. It does not create Docker images or leave
plaintext PostgreSQL backups.

Limits: this same-host snapshot is NOT offsite disaster recovery and archive
parsing is NOT a full restore test. VPS disk loss could destroy both the live
database and this snapshot. No automated backup cadence or remote retention
policy is configured yet. A remote destination and restore acceptance are
needed before storing real customer data.

The existing backup and full local restore can be complemented by the
separate-machine verification documented in
[Production database recovery acceptance](../docs/PRODUCTION-DATABASE-RECOVERY-ACCEPTANCE.md).
Only encrypted archives cross machine boundaries; the independent host uses
its own Doppler identity and an isolated RAM-only PostgreSQL restore.

## Full encrypted restore validation

Cloud now includes scripts/production-restore-drill.sh. It restores the
production age-encrypted backup into a disposable, isolated, tmpfs-only
PostgreSQL 17 container and checks checksum ledger, security triggers
and core metadata against the live DB. It does not modify production.
See docs/PRODUCTION-DATABASE-RECOVERY-ACCEPTANCE.md.

This is NOT offsite disaster recovery. Migrations 007–012 remain blocked
until an independently downloaded remote encrypted archive passes
another full restore. Never treat a same-host backup as offsite.


## Schema 007-012 production-snapshot rehearsal

The optional --rehearse-schema switch on
scripts/production-restore-drill.sh invokes the real Cloud migration
engine against an isolated RAM-backed database cloned from the latest
encrypted production snapshot. On 27 October 2026 it passed migration
006 to 012 with preserved metadata and idempotent replay, while
production remained on 006. Offsite full restore is still required
before live migration.
