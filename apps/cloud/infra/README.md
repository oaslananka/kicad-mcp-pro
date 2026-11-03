# Production infrastructure

For a NEW server/domain, start with [Portable Doppler-first deployment](PORTABLE-DEPLOY.md).
For the CURRENT verified production VPS, follow [Production deployment](PRODUCTION-DEPLOY.md).
Never run the fresh-install workflow against the existing app/database.


The reviewed production Docker Compose deployment now runs on the existing
VPS and healthy Cloudflare Tunnel at:
https://kicad-mcp-pro.oaslananka.dev

An isolated PostgreSQL 17 container, private Docker database network,
persistent volume and one active plus one rollback application image are installed.
No host-side database or application ports are published. Cloudflare tunnel
ingress is shared with existing services, which must not be interrupted.

Doppler kicad-mcp-pro/prd_cloud holds runtime configuration and secrets;
GitHub Secrets contains only DOPPLER_TOKEN (used for the optional manually
triggered config check, not deployment). CI-gated application deployment now
uses an outbound-only VPS user timer and the `Production Deployment` GitHub
Actions workflow, with one rollback app image and no staging. This existing
VPS/tunnel setup needs no OpenTofu re-provisioning; provision additional
resources only for a demonstrated requirement and avoid duplicate services.

Public premium UI and anonymous token enforcement are deployed. GitHub OAuth
start is configured, but the actual user callback/session and AI-client OAuth
are not yet fully accepted; local KiCad device execution remains unavailable. See infra/PRODUCTION-DEPLOY.md and
docs/OAUTH-PRODUCTION-ACCEPTANCE.md.

## Controlled versioned PostgreSQL migrations

Use the reviewed, checksum-verified migration runner instead of concatenating
SQL files manually. It has **no startup hook** and runs no production command
from a pull request. It requires an explicit flag and a Doppler-injected DB URL:

    doppler run -- npm run db:migrate -- --status
    doppler run -- npm run db:migrate -- --apply

The status operation does not create tables. Apply takes a PostgreSQL
transaction-scoped advisory lock, verifies the stored filename/SHA-256 ledger,
and applies *all* pending SQL versions atomically. Re-running a completed
migration does nothing. Modified or missing historic migrations, version gaps
and partially hand-created schemas fail closed; there is no automatic
"repair"/baseline or silent destructive rollback. Use an operator-reviewed
recovery procedure for existing deployments.

Before a production apply: choose and independently verify the Doppler
environment, take a database backup, rehearse a restore, inspect the SQL
diff and hold deployment while database schema is being updated. The runner
does not provision databases, validate backup restore or deploy application
containers. Migration 003 is pinned to Better Auth 1.7.13; upgrades require a
separate schema review. CI tests only in a disposable PostgreSQL 17 schema.

## Disposable PostgreSQL backup/restore acceptance

The CI workflow runs scripts/ci-db-restore-drill.sh using the same secret-free
OCI image it just built. The script creates its own two disposable PostgreSQL
17 containers and an internal-only Docker network, with no host-bound ports.
The database password is generated anew in memory for this disposable
fixture; no Doppler or application environment is read.

It explicitly applies reviewed migrations 001–006, seeds synthetic
device/project/client metadata and an OAuth revocation cutoff, streams a
PostgreSQL custom-format dump into an empty target with restore-on-error, and
checks the following:
- migration checksum ledger is retained and repeat application is harmless;
- metadata, per-client project grant and revocation cutoff survive;
- all OAuth issuance/replay triggers are present after restore;
- a late synthetic refresh-token INSERT is rejected by SQLSTATE 23514;
- disposable containers and isolated network are cleaned up on completion.

For local reproduction, build the reviewed OCI image and run:
    bash scripts/ci-db-restore-drill.sh kicad-mcp-pro-cloud:ci

This disposable test is not a production restore: it does not validate
offsite backup retention, remote restore RTO/RPO or full database recovery.
Production has no staging, but retains one rollback application image. See
the production backup/restore limits in infra/PRODUCTION-DEPLOY.md.
