#!/usr/bin/env bash
# Initial installation on a NEW owner-controlled VPS only.
# Requires operator-provisioned Docker, Doppler CLI and a config-scoped service token.
# Never called by CI or the existing VPS release timer.
set -euo pipefail
mode=${1:-preflight}
[[ "$mode" == preflight || "$mode" == install || "$mode" == preflight-pr || "$mode" == install-pr ]] || {
  echo 'Usage: bootstrap-production-vps.sh [preflight|install|preflight-pr PR_NUMBER HEAD_SHA|install-pr PR_NUMBER HEAD_SHA]' >&2; exit 2
}
acceptance=false
pr_number=''
if [[ "$mode" == preflight-pr || "$mode" == install-pr ]]; then
  acceptance=true
  pr_number=$2
  [[ $# == 3 && "$2" =~ ^[1-9][0-9]{0,8}$ && "$3" =~ ^[a-f0-9]{40}$ ]] || {
    echo 'Acceptance requires explicit PR number and exact 40-character head SHA' >&2; exit 2
  }
else
  [[ $# -le 1 ]] || { echo 'Unexpected bootstrap arguments' >&2; exit 2; }
fi
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$root"
for command in docker git node doppler curl; do
  command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 2; }
done
[[ $(git remote get-url origin) == 'https://github.com/oaslananka/kicad-mcp-pro.git' ]] || { echo 'Unexpected source repository' >&2; exit 2; }
[[ -z $(git status --porcelain) ]] || { echo 'Refusing dirty checkout' >&2; exit 2; }
remote_main=$(git ls-remote origin refs/heads/main | awk '{print $1}')
[[ "$remote_main" =~ ^[a-f0-9]{40}$ ]] || { echo 'Current main SHA unavailable' >&2; exit 2; }
if [[ "$acceptance" == true ]]; then
  # Production main cannot be merged as a prerequisite for testing this PR:
  # that would activate the existing VPS release watcher. Only an exact,
  # same-repo open PR with successful CI AND security scans may be installed.
  revision=$(git rev-parse HEAD)
  [[ "$revision" == "$3" ]] || { echo 'Acceptance checkout HEAD does not match supplied SHA' >&2; exit 2; }
  advertised=$(git ls-remote origin "refs/pull/$2/head" | awk '{print $1}')
  [[ "$advertised" == "$revision" ]] || { echo 'PR ref does not match reviewed checkout' >&2; exit 2; }
  pr_payload=$(curl --fail --silent --show-error --max-time 15 \
    --header 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/oaslananka/kicad-mcp-pro/pulls/$2")
  checks_payload=$(curl --fail --silent --show-error --max-time 15 \
    --header 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/oaslananka/kicad-mcp-pro/commits/$revision/check-runs?per_page=100")
  runs_payload=$(curl --fail --silent --show-error --max-time 15 \
    --header 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/oaslananka/kicad-mcp-pro/actions/workflows/cloud-ci.yml/runs?head_sha=$revision&event=pull_request&per_page=20")
  printf '%s\0%s\0%s' "$pr_payload" "$checks_payload" "$runs_payload" |
    node scripts/verify-bootstrap-pr.mjs "$2" "$revision" "$remote_main"
else
  [[ $(git rev-parse HEAD) == $(git rev-parse refs/remotes/origin/main) ]] || {
    echo 'Installation must use a locally verified current origin/main' >&2; exit 2
  }
  [[ "$remote_main" == "$(git rev-parse HEAD)" ]] || { echo 'Source is not current remote main: abort' >&2; exit 2; }
fi
docker info >/dev/null
docker compose version >/dev/null
# Refuse existing KiCad state BEFORE fetching any configuration/secret.
if docker container inspect kicad-cloud-app-1 >/dev/null 2>&1 || docker container inspect kicad-cloud-db-1 >/dev/null 2>&1; then
  echo 'Existing KiCad production containers detected: refusing first-install workflow' >&2; exit 1
fi
if docker volume inspect kicad-cloud_production_database >/dev/null 2>&1; then
  echo 'Existing database volume detected: refusing potential data reuse' >&2; exit 1
fi
# A previous partial installation might leave just the Cloudflare edge
# container, even if its old ingress network was renamed in Doppler.
if docker container inspect kicad-cloud-edge-cloudflared-1 >/dev/null 2>&1; then
  echo 'Existing KiCad Cloudflare tunnel container detected: refusing first install' >&2; exit 1
fi
[[ "${KICAD_DOPPLER_SCOPED:-}" == true ]] || { echo 'Use a directory-scoped, read-only Doppler service token (KICAD_DOPPLER_SCOPED=true)' >&2; exit 2; }
scripts/doppler-runtime.sh node scripts/portable-config.mjs validate
# First-install settings are fetched multiple times as isolated processes.
# Detect changed Doppler values (including secrets) across the image build
# without storing or printing those values in a repo artifact or shell log.
config_fingerprint=$(scripts/doppler-runtime.sh node scripts/portable-config.mjs fingerprint)
[[ "$config_fingerprint" =~ ^[a-f0-9]{64}$ ]] || {
  echo 'Invalid Doppler configuration fingerprint; abort' >&2; exit 2
}
network=$(scripts/doppler-runtime.sh node scripts/portable-config.mjs network)
[[ "$network" != ops_internal ]] || { echo 'Use a dedicated KICAD_TUNNEL_NETWORK on a new VPS; do not reuse the legacy shared network' >&2; exit 2; }
# Probe only secret presence; never emit the Tunnel token.
scripts/doppler-runtime.sh node -e 'if(!process.env.CLOUDFLARE_TUNNEL_TOKEN)process.exit(2)'
public_origin=$(scripts/doppler-runtime.sh node scripts/portable-config.mjs origin)
expected_google=$(scripts/doppler-runtime.sh node scripts/portable-config.mjs google)
[[ ! -e .env ]] || { echo 'Plaintext .env is forbidden for production' >&2; exit 2; }
if docker network inspect "$network" >/dev/null 2>&1; then
  echo 'Ingress network already exists: refusing ambiguous ownership/partial installation' >&2; exit 1
fi
scripts/doppler-runtime.sh docker compose -f infra/compose.production.yml config --quiet
scripts/doppler-runtime.sh docker compose -f infra/compose.cloudflare.yml config --quiet
printf 'New VPS preflight passed: reviewed Git source, Doppler config, isolated ingress selector and Compose syntax.\n'
if [[ "$mode" == preflight || "$mode" == preflight-pr ]]; then exit 0; fi
# All install modes are intentionally explicit. Normal installation requires
# successful main push CI; PR acceptance already checked its security/CI
# gates before secret access or Docker provisioning.
revision=$(git rev-parse HEAD)
if [[ "$acceptance" == false ]]; then
ci_payload=$(curl --fail --silent --show-error --max-time 15 \
  --header 'Accept: application/vnd.github+json' \
  'https://api.github.com/repos/oaslananka/kicad-mcp-pro/actions/workflows/cloud-ci.yml/runs?branch=main&event=push&per_page=20')
if ! printf '%s' "$ci_payload" | node -e '
let body=""; process.stdin.on("data",part=>body+=part);
process.stdin.on("end",()=>{
 try{
  const runs=JSON.parse(body).workflow_runs;
  if(!Array.isArray(runs)||!runs.some(r=>r.head_sha===process.argv[1]&&
     r.event==="push"&&r.status==="completed"&&r.conclusion==="success"))process.exitCode=1;
 }catch{process.exitCode=1;}
});' "$revision"; then
  echo 'Exact-main successful CI proof unavailable; first install blocked' >&2
  exit 1
fi
fi
# CI and review were checked before configuration access. The source can
# nevertheless change while the first image builds. Refuse a superseded PR,
# a closed PR, or an advanced main before any database is created/migrated.
assert_reviewed_source_still_current() {
  [[ "$(git rev-parse HEAD)" == "$revision" &&
     -z "$(git status --porcelain)" ]] || {
    echo 'Reviewed checkout changed during initial installation; abort' >&2; return 1
  }
  local latest_main
  latest_main=$(git ls-remote origin refs/heads/main | awk '{print $1}')
  [[ "$latest_main" == "$remote_main" ]] || {
    echo 'Remote main advanced during installation; abort before database start' >&2; return 1
  }
  if [[ "$acceptance" == true ]]; then
    local latest_pr latest_payload
    latest_pr=$(git ls-remote origin "refs/pull/$pr_number/head" | awk '{print $1}')
    [[ "$latest_pr" == "$revision" ]] || {
      echo 'Reviewed PR head changed during installation; abort before database start' >&2; return 1
    }
    latest_payload=$(curl --fail --silent --show-error --max-time 15       --header 'Accept: application/vnd.github+json'       "https://api.github.com/repos/oaslananka/kicad-mcp-pro/pulls/$pr_number")
    if ! printf '%s' "$latest_payload" | node -e '
      let input="";process.stdin.on("data",b=>input+=b);
      process.stdin.on("end",()=>{
        try{
          const p=JSON.parse(input),sha=process.argv[1],main=process.argv[2],
            num=Number(process.argv[3]),repo="oaslananka/kicad-mcp-pro";
          if(p.number!==num||p.state!=="open"||p.head?.sha!==sha||
             p.base?.sha!==main||p.base?.ref!=="main"||
             p.head?.repo?.full_name!==repo||p.base?.repo?.full_name!==repo)
            process.exitCode=1;
        }catch{process.exitCode=1;}
      });' "$revision" "$remote_main" "$pr_number"; then
      echo 'Reviewed PR closed or changed during installation; abort before database start' >&2
      return 1
    fi
  fi
}
# Acceptance installations never enable a timer and cannot be automatically
# deployed from main while the PR is still open.
# Does not configure DNS, provider OAuth, any other account or existing VPS.
assert_reviewed_source_still_current
# Build before allocating the dedicated ingress network. If PR/main changes
# while building, stop without leaving a half-provisioned network or database.
docker build --pull=false --build-arg "APP_REVISION=$revision" -t kicad-mcp-pro-cloud:production .
assert_reviewed_source_still_current
latest_fingerprint=$(scripts/doppler-runtime.sh node scripts/portable-config.mjs fingerprint)
if [[ "$latest_fingerprint" != "$config_fingerprint" ]]; then
  echo 'Doppler configuration changed during image build; abort before network/database start' >&2
  exit 1
fi
docker network create --driver bridge "$network" >/dev/null
scripts/doppler-runtime.sh docker compose -f infra/compose.production.yml up -d db
healthy=false
for _ in $(seq 1 30); do
  status=$(docker inspect kicad-cloud-db-1 --format '{{.State.Health.Status}}')
  if [[ "$status" == healthy ]]; then healthy=true; break; fi
  sleep 2
done
[[ "$healthy" == true ]] || { echo 'Database did not become healthy; installation incomplete' >&2; exit 1; }
# This is a newly created database. Existing databases require separate
# backup, review and operator-authorized migration, not this installer.
scripts/doppler-runtime.sh docker compose -f infra/compose.production.yml run --rm app node dist/migrations-cli.js --apply
scripts/doppler-runtime.sh docker compose -f infra/compose.production.yml up -d app
scripts/doppler-runtime.sh docker compose -f infra/compose.cloudflare.yml up -d cloudflared
# Cloudflare Tunnel, DNS and TLS may need a short time to become usable.
# Bounded readiness never masks a wrong domain, route or revision.
public_ready=false
for _ in $(seq 1 20); do
  observed=$(curl --fail --silent --show-error --max-time 7 \
    "$public_origin/health" 2>/dev/null | \
    node -e 'let b="";process.stdin.on("data",c=>b+=c);process.stdin.on("end",()=>{try{const h=JSON.parse(b);if(h.status==="ok")process.stdout.write(h.revision??"")}catch{}})' || true)
  if [[ "$observed" == "$revision" ]]; then public_ready=true; break; fi
  sleep 3
done
[[ "$public_ready" == true ]] || {
  echo 'Public HTTPS ingress did not reach the expected reviewed revision; install incomplete' >&2
  exit 1
}
# Public routing and OAuth registration must be accepted before installation.
PUBLIC_ORIGIN="$public_origin" EXPECTED_GOOGLE_OAUTH="$expected_google" EXPECTED_REVISION="$revision" node scripts/production-smoke.mjs
# A second VPS polling the same GitHub main would trigger unapproved parallel
# production releases. Enabling its timer is a separate owner-controlled cutover.
if [[ "$acceptance" == true ]]; then
  printf 'PASS: PR #%s at %s accepted in a fresh, timer-free VPS instance: %s\n' "$2" "$revision" "$public_origin"
else
  printf 'PASS: new VPS initial installation verified at %s\n' "$public_origin"
fi
printf 'Release timer NOT enabled. Accept the owner cutover and stop the old VPS timer before enabling the new one.\n'
