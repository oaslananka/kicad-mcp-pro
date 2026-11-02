# Portable, Doppler-first Cloud deployment

**Scope:** one fresh, owner-controlled Linux VPS and one configured HTTPS
hostname; existing production remains intact. A green test/CI run means this
installer is source-validated, **not** that an arbitrary new VPS, provider
registration or DNS cutover has been independently accepted.

## Contract and secrets boundary

- Doppler is the canonical source of **static** runtime settings and secrets.
  No `.env`, extra GitHub Actions secrets, GitHub Variables or secret-containing
  OCI build arguments are needed. User sessions, OAuth grants and dynamic
  signing keys/metadata still live in encrypted/controlled PostgreSQL state.
- The only user-created GitHub repository secret is `DOPPLER_TOKEN`: a **read-only,
  production-config-scoped service token**. `Production Deployment` now uses it
  to resolve `PUBLIC_ORIGIN` for live acceptance; manual config validation also
  uses it. Never authorize it on PR code or print its contents.
- Every VPS requires its **own** read-only Doppler service token as a bootstrap
  credential, registered via the official CLI at the deployment worktree's
  filesystem scope. The VPS cannot obtain a token merely because GitHub has
  one; GitHub Actions has no VPS admin/SSH access. A scoped token is itself a
  bootstrap credential stored by the Doppler CLI, not inside the app's Doppler
  secrets or in Git. Prefer separate, independently revocable GitHub/VPS tokens
  to the same production config. In directory-scoped mode, an inherited
  `DOPPLER_TOKEN`, `DOPPLER_PROJECT` or `DOPPLER_CONFIG` could override the
  directory selection: the wrapper explicitly refuses these combinations. See official Doppler
  service-token docs.
- Domain, OAuth issuer/JWKS/audience, PostgreSQL password, GitHub/Google OAuth
  client credentials, Better Auth root secret, management identity, allowed
  origins and dedicated Docker ingress network name are set in Doppler.
- The **source GitHub repository and deploy workflow logic** remain fixed by
  design: deployments from other repos or untested pull requests are rejected.

### Required Doppler keys (new VPS, GitHub-only login)

| Name | Meaning |
| --- | --- |
| `PUBLIC_ORIGIN` | Exact HTTPS origin, no trailing slash or path |
| `OAUTH_ISSUER` | `PUBLIC_ORIGIN` + `/api/auth` |
| `OAUTH_JWKS_URL` | `PUBLIC_ORIGIN` + `/api/auth/jwks` |
| `OAUTH_AUDIENCE` | `PUBLIC_ORIGIN` + `/mcp` |
| `KICAD_DB_PASSWORD` | Fresh production PostgreSQL password |
| `AUTH_MODE` | Exactly `builtin` for new VPS first launch (not `external`) |
| `BETTER_AUTH_SECRET` | Independent cryptographically random auth root secret, at least 32 characters |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | New domain's GitHub OAuth app credentials |
| `KICAD_TUNNEL_NETWORK` | Dedicated Docker bridge name for this VPS, e.g. `kicad_private_ingress` |
| `CLOUDFLARE_TUNNEL_TOKEN` | Token for a **dedicated, remotely managed** Cloudflare Tunnel |

Optional when explicitly configured: `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, `MANAGEMENT_CLIENT_ID`, `ALLOWED_ORIGINS`
(comma-separated exact HTTPS origins; invalid entries fail preflight) and backup
age keys. When both Google credentials are present, production smoke checks
that the Google login option is displayed; no credential value is logged. Provider pairs must be complete; OAuth providers need their own
registered callback URLs for the **new** domain. `PAIRING_DEVICE_API_ENABLED`
and `CONNECTOR_WS_ENABLED` must stay **false** until separate device-ingress
security acceptance. The portability bootstrap rejects them if enabled.

`DATABASE_URL` is intentionally composed inside Compose from the dedicated
container's fixed service hostname and database name, using the Doppler-provided
`KICAD_DB_PASSWORD` through `PGPASSWORD`; this avoids duplicating a credential
in a connection URL. Static internal Docker service names need not match your
public hostname.

## One-time external preparation (not automatic account mutations)

1. Control the target VPS (Linux/systemd, Docker Engine + Compose, Git, Node 24,
   Doppler CLI and outbound HTTPS). Install and harden them using trusted official
   distribution instructions. The installer does not run unattended sudo,
   cloud provisioning, package-manager bootstrap or provider API writes.
2. Create a fresh Doppler project/config for this deployment and fill the keys
   above. Register the same **config's separate scoped token** as GitHub's sole
   user-created secret, `DOPPLER_TOKEN`. Protect the `production` GitHub
   environment; validate token/config alignment before merging changes to main.
3. Create a dedicated Cloudflare Tunnel and set its public hostname to the new
   domain, pointing to `http://kicad-cloud-app-1:8787` on the dedicated Docker
   ingress network. Configure the hostname's DNS mapping in Cloudflare and
   verify HTTPS/Host and OAuth redirect endpoints. No Worker or additional WAF rule
   is required for the **disabled-device** baseline. A managed tunnel token
   grants control of that tunnel; keep it private in Doppler.
4. Register an OAuth application at GitHub with the correct callback URL:
   `https://YOUR_DOMAIN/api/auth/callback/github`. Update/rotate the provider
   credential pairs in Doppler; changing `PUBLIC_ORIGIN` alone **does not**
   update the external provider registration or the DNS/Tunnel route.
5. Clone `oaslananka/kicad-mcp-pro` from reviewed `main` into a fresh
   **dedicated, clean deployment worktree** (not a shared active development
   checkout). From that directory, run
   `bash scripts/setup-vps-doppler.sh YOUR_DOPPLER_PROJECT YOUR_DOPPLER_CONFIG`.
   It securely prompts for a read-only, config-scoped VPS service token on a
   TTY, uses `doppler setup --no-interactive --scope` for this exact directory,
   and checks configuration without printing values. Do not include the token
   in command arguments, shell history or plaintext files. Set the **nonsecret
   bootstrap selector** `KICAD_DOPPLER_SCOPED=true` in the installer shell.

## Independent, unmerged PR acceptance (before any production release)

**The acceptance order matters:** merging this PR into `main` before the
independent VPS trial could trigger a release watcher if one is installed. To test
the PR code *before merging*, the installer has two explicit,
non-production-watcher modes: `preflight-pr` and `install-pr`. They require
an **exact full commit SHA** and a real, same-repository GitHub PR number, and
fail closed unless the checked-out SHA equals the advertised GitHub PR ref,
the PR still targets the current `main`, the real PR GitHub Actions CI run
has succeeded for that SHA, and the current CodeQL, Semgrep, SonarCloud,
Codacy, GitGuardian and other expected check runs have all completed
successfully. Pending/neutral/failing/missing gates, forks, stale checkouts,
closed PRs or changed `main` abort before secret access and Docker changes.

On a **separate, owner-authorized, empty VPS** with independently registered
HTTPS hostname, dedicated Tunnel and Doppler config, clone from the canonical
repository and explicitly check out the reviewed PR SHA:

```bash
git clone https://github.com/oaslananka/kicad-mcp-pro.git kicad-cloud-acceptance
cd kicad-cloud-acceptance/apps/cloud
git fetch origin refs/pull/63/head
reviewed_sha=$(git rev-parse FETCH_HEAD)
git show --no-patch --format='%H %s' "$reviewed_sha"
# Review this exact commit and its successful PR checks before continuing.
git checkout --detach "$reviewed_sha"

# On this fresh VPS only, register this host's own read-only Doppler token.
bash scripts/setup-vps-doppler.sh YOUR_DOPPLER_PROJECT YOUR_DOPPLER_CONFIG
export KICAD_DOPPLER_SCOPED=true
bash scripts/bootstrap-production-vps.sh preflight-pr 63 "$reviewed_sha"
# Explicit first-install acceptance; requires live DNS/Tunnel/OAuth configuration:
bash scripts/bootstrap-production-vps.sh install-pr 63 "$reviewed_sha"
```

The `reviewed_sha` variable is captured **once**, printed for independent
operator review and checked against GitHub's advertised PR ref and exact-head
CI/security gates on every bootstrap invocation. Never treat it as a moving
branch alias or reuse a SHA after a later PR update. Do not run these commands on the
already deployed production VPS. No `main` merge, production GitHub
secret modification, live release timer installation, provider account
write or additional-resource provisioning is part of this PR acceptance mode.
The PR trial must use a **separate HTTPS hostname** and its own Doppler
config and OAuth provider registration. During installation, the verified PR head, PR open state, unchanged main and
clean local worktree are checked again before creating resources and after the
OCI image build; if anything changes mid-build, it aborts before allocating
the ingress network or touching the database. A candidate image may remain
after this refusal; review it rather than blindly retrying. The installer
also pins a secret-safe, keyed fingerprint of the Doppler configuration
during preflight and verifies it again after the image build before allocating
the network or database. A credential, hostname, OAuth or network change
during that build stops the initial installation without printing the changed
value. Do not rotate the Doppler config while an installation is in progress;
this extra check is not a substitute for controlled secret rotation once
a persistent database is running.
The installation only verifies that
the login form and OAuth discovery are available; the operator must also
complete a real, owner-controlled OAuth round trip and check the approved
callback URL separately before final acceptance. Accept actual backup,
next-release and rollback behavior separately; do not confuse CI and a
successful first install with these post-install recovery guarantees.

## New-server execution (explicit, safe by default)

**After review and authorized merging**, the normal `main`-only installer
continues to demand a clean checkout of the exact current remote `main` and
a successful push CI run on that commit. It intentionally rejects PR
checkouts regardless of their passing scans. From the clean deployment
worktree with the scoped Doppler credential:

```bash
export KICAD_DOPPLER_SCOPED=true
bash scripts/bootstrap-production-vps.sh preflight
# Only after the owner has prepared DNS, provider callback and a fresh VPS:
bash scripts/bootstrap-production-vps.sh install
```

Both `preflight` and `preflight-pr` make no deployment/network/database changes. It validates the
source identity, clean checked-out `origin/main`, Docker/Compose access,
Doppler values without printing secrets, disabled connector flags, and both
Compose files. It rejects a shared `ops_internal` ingress, existing KiCad app,
database or edge tunnel containers, existing database volumes, a name-colliding
ingress network and a missing Cloudflare token. This is intentionally **not** a migration or upgrade
command for an already deployed VPS.

`install` explicitly creates only the named dedicated Docker ingress bridge,
builds the reviewed source, starts a *fresh* PostgreSQL database, runs the
checksummed schema migration in that fresh DB, starts the app and isolated
`cloudflared` container, waits a bounded time for the expected public HTTPS
revision, then validates OAuth/MCP read-only routes. It deliberately **does not**
enable the CI-gated user timer: two VPS watchers polling one `main` branch
could otherwise deploy in parallel without an approved cutover. On a failed first installation,
stop and inspect the partial resources; do not blindly rerun against the
existing database or purge shared Docker resources. Offsite backup scheduling,
first live OAuth owner approval, authorized release-watcher cutover, domain transfer, physical KiCad device pairing
and any provider configuration change remain **separate acceptance tasks**.

### Release-watcher cutover (separate operator action)

After an independent installation acceptance and an **authorized main
merge/release decision**, first disable the prior VPS's
`kicad-cloud-production.timer` under its owning `systemd --user` instance
and verify that it stopped (an owner action performed **on the old VPS**).
Verify the new destination is the one configured by both the GitHub and VPS
production Doppler tokens; the old production timer must no longer deploy
that same `main` stream. On the **new VPS**, ensure the checked-out commit
matches the exact *current remote main*, not the unmerged PR acceptance SHA,
and that the per-user systemd manager survives logout/reboot:
`loginctl show-user "$(id -un)" -p Linger --value` should report `yes`.
If it reports `no`, the authorized VPS administrator must separately enable
user lingering (e.g. `sudo loginctl enable-linger "$(id -un)"`) before cutover.

Only **after** the old watcher is demonstrably disabled, the intended target
is checked, and lingering is enabled, explicitly acknowledge the handover:

```bash
export KICAD_DOPPLER_SCOPED=true
export KICAD_WATCHER_CUTOVER_CONFIRMED=old-watcher-disabled-and-destination-verified
bash scripts/install-production-deploy-timer.sh
```

For a new scoped-Doppler VPS the installer rejects absent acknowledgement,
disabled user lingering or an unavailable user manager **before touching
systemd unit files**. For every VPS it also rejects unmerged PR checkouts,
dirty Git worktrees and any checkout behind current remote `main`. These
checks cannot remotely prove that the old VPS is stopped: the confirmation
must reflect an actual operator-verified cutover, not a guess. The existing
production timer is not modified by this PR. Do not run old and new watchers
concurrently; there is one `main` release stream and one production
GitHub `DOPPLER_TOKEN` destination. The cutover is **never** a side effect
of first installation or PR acceptance.

On an **existing** production VPS, keep its existing shared Tunnel and Compose
network (`ops_internal` legacy default), release timer and Doppler selection.
Do **not** run the first-install workflow or create a second `cloudflared`
instance. For normal application releases, `main` CI gates the outbound-only
VPS deployment timer and GitHub independently checks the exact production
revision at the `PUBLIC_ORIGIN` it reads from the same Doppler config.

## Backups and configuration changes (operator-controlled)

For manual encrypted offsite backup/restore on a configured deployment,
provide `OFFSITE_REMOTE_SSH` and `OFFSITE_REMOTE_DIR` in the **source VPS's
Doppler config**, not in a new `.env` file, and execute
`bash scripts/doppler-runtime.sh bash scripts/offsite-backup-push.sh` from the
reviewed deployment worktree. The independent restore machine must already
have its own authorized age decryption identity from Doppler, plus reviewed
SSH access; optional `OFFSITE_RESTORE_DOPPLER_PROJECT` and
`OFFSITE_RESTORE_DOPPLER_CONFIG` select that independent machine's Doppler
configuration. Existing backups remain encrypted end to end and are never
implicitly copied during application installation. The separately installed
daily user-level timer uses the **same Doppler configuration** via
`scripts/doppler-runtime.sh`; it does not create or consume a second endpoint
configuration file. Only after an approved destination is provisioned, the
independent restore machine is accepted, and the source environment passes
the fail-closed preflight, run `bash scripts/install-offsite-backup-timer.sh`
on the intended source VPS. Application installation and deployment never
install or enable this timer implicitly.

Doppler is a *configuration source*, not a magic live reconfiguration engine:
existing PostgreSQL passwords are not rotated merely by changing
`KICAD_DB_PASSWORD` (Postgres bootstrap initialization reads it only for a
fresh volume); `BETTER_AUTH_SECRET` must not be casually replaced because
existing encrypted signing/provider data may become unreadable. OAuth client
secret rotation requires updating the provider, and public domain changes
require DNS, Tunnel and registered callback URL changes. Recreate only the
appropriate service after reviewing config/secret rotation and recovery;
never invoke the fresh-VPS installer against existing production data.

## Acceptance before saying portable deployment is done

- Run offline fixture checks and CI; no real Doppler data appears in logs.
- Prove one **independently provisioned disposable VPS** end to end: scoped
  Doppler token, fresh schema, dedicated ingress, live OAuth callback, public
  smoke, no public app/DB ports, CI-gated next commit and app rollback.
- Restore an encrypted database snapshot into a second clean host and confirm
  the data/recovery policy for the chosen deployment. A fresh installation
  does not imply automated offsite backup scheduling.
- Confirm that changing only Doppler + external DNS/OAuth provider settings
  suffices for **another** VPS/domain without editing source code. Record
  recovery/rollback evidence before claiming deployment portability accepted.

Official documentation: https://docs.doppler.com/docs/service-tokens ;
https://developers.cloudflare.com/tunnel/get-started/ ;
https://docs.docker.com/reference/compose-file/networks/ .
