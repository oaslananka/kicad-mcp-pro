#!/usr/bin/env bash
# Offline integration contract for bootstrap-production-vps.sh.
# All Git/Docker/Doppler/curl/node calls are intercepted by synthetic binaries;
# no cloud provider, remote repository or live Docker daemon is contacted.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$root"
sandbox=$(mktemp -d "${TMPDIR:-/tmp}/kicad-bootstrap-fixture.XXXXXXXX")
chmod 700 "$sandbox"
bin="$sandbox/bin"
mkdir -m 700 "$bin"
log="$sandbox/calls.log"
trap 'rm -rf -- "$sandbox"' EXIT
mock_head='1697bf37f689aac3f16eca2dc0b5827f055e9795'
real_node=$(command -v node)
cat > "$bin/git" <<'MOCK'
#!/usr/bin/env bash
set -eu
case "$*" in
  'remote get-url origin') echo 'https://github.com/oaslananka/kicad-mcp-pro-cloud.git';;
  'status --porcelain')
    if [[ "${MOCK_DIRTY_AFTER_BUILD:-}" == yes ]] && grep -q '^docker build ' "$MOCK_LOG"; then
      echo ' M scripts/bootstrap-production-vps.sh'
    fi;;
  'rev-parse HEAD') echo "$MOCK_HEAD";;
  'rev-parse refs/remotes/origin/main') echo "$MOCK_BASE";;
  'ls-remote origin refs/pull/63/head')
    if [[ "${MOCK_ADVANCE_AFTER_BUILD:-}" == pr ]] && grep -q '^docker build ' "$MOCK_LOG"; then
      printf '%s refs/pull/63/head\n' 'ffffffffffffffffffffffffffffffffffffffff'
    else
      echo "$MOCK_HEAD refs/pull/63/head"
    fi;;
  'ls-remote origin refs/heads/main')
    if [[ "${MOCK_ADVANCE_AFTER_BUILD:-}" == main ]] && grep -q '^docker build ' "$MOCK_LOG"; then
      printf '%s refs/heads/main\n' 'ffffffffffffffffffffffffffffffffffffffff'
    else
      printf '%s\n' "$MOCK_BASE refs/heads/main"
    fi;;
  *) exit 98;;
esac
MOCK
cat > "$bin/docker" <<'MOCK'
#!/usr/bin/env bash
set -eu
printf 'docker %s\n' "$*" >> "$MOCK_LOG"
if [[ "$*" == 'container inspect kicad-cloud-app-1' && "$MOCK_EXISTING" == container ]]; then exit 0; fi
if [[ "$*" == 'volume inspect kicad-cloud_production_database' && "$MOCK_EXISTING" == volume ]]; then exit 0; fi
if [[ "$*" == 'container inspect kicad-cloud-edge-cloudflared-1' && "$MOCK_EXISTING" == edge ]]; then exit 0; fi
case "$*" in
  info|'compose version'|'compose -f infra/compose.production.yml config --quiet'|'compose -f infra/compose.cloudflare.yml config --quiet') exit 0;;
  'container inspect '*|'volume inspect '*|'network inspect '*) exit 1;;
  'network create --driver bridge '*|'build --pull=false '*) exit 0;;
  'inspect kicad-cloud-db-1 --format '*) echo healthy; exit 0;;
  'compose -f infra/compose.production.yml up -d db'|'compose -f infra/compose.production.yml up -d app'|'compose -f infra/compose.cloudflare.yml up -d cloudflared'|'compose -f infra/compose.production.yml run --rm app node dist/migrations-cli.js --apply') exit 0;;
  *) exit 99;;
esac
MOCK
cat > "$bin/doppler" <<'MOCK'
#!/usr/bin/env bash
set -eu
printf 'doppler %s\n' "$*" >> "$MOCK_LOG"
[[ "$1" == run && "$2" == --no-read-env && "$3" == -- ]] || exit 97
shift 3
if [[ "${MOCK_DOPPLER_ROTATE_AFTER_BUILD:-}" == yes && "$*" == 'node scripts/portable-config.mjs fingerprint' ]] &&
   grep -q '^docker build ' "$MOCK_LOG"; then
  export BETTER_AUTH_SECRET='second-synthetic-auth-secret-after-image-build'
fi
exec "$@"
MOCK
cat > "$bin/curl" <<'MOCK'
#!/usr/bin/env bash
set -eu
printf 'curl %s\n' "$*" >> "$MOCK_LOG"
if [[ "$*" == *'actions/workflows/ci.yml/runs'* ]]; then
  if [[ "$MOCK_CI_PASS" == yes ]]; then
    if [[ "$*" == *'event=pull_request'* ]]; then
      printf '{"workflow_runs":[{"head_sha":"%s","event":"pull_request","status":"completed","conclusion":"success"}]}' "$MOCK_HEAD"
    else
      printf '{"workflow_runs":[{"head_sha":"%s","event":"push","status":"completed","conclusion":"success"}]}' "$MOCK_HEAD"
    fi
  else
    printf '{"workflow_runs":[]}'
  fi
elif [[ "$*" == *'/pulls/63'* ]]; then
  state=open
  if [[ "${MOCK_CLOSE_AFTER_BUILD:-}" == yes ]] && grep -q '^docker build ' "$MOCK_LOG"; then
    state=closed
  fi
  printf '{"number":63,"state":"%s","head":{"sha":"%s","repo":{"full_name":"oaslananka/kicad-mcp-pro-cloud"}},"base":{"sha":"%s","ref":"main","repo":{"full_name":"oaslananka/kicad-mcp-pro-cloud"}}}' "$state" "$MOCK_HEAD" "$MOCK_BASE"
elif [[ "$*" == *'/check-runs?per_page=100'* ]]; then
  if [[ "$MOCK_CI_PASS" == yes ]]; then
    printf '{"check_runs":['
    id=1
    for name in 'check' 'SonarCloud Code Analysis' 'Codacy Static Code Analysis' 'CodeQL' 'semgrep-cloud-platform/scan' 'GitGuardian Security Checks' 'Socket Security: Pull Request Alerts' 'Analyze (javascript-typescript)' 'Analyze (actions)'; do
      [[ $id == 1 ]] || printf ','
      printf '{"id":%s,"name":"%s","status":"completed","conclusion":"success"}' "$id" "$name"
      id=$((id+1))
    done
    printf ']}'
  else
    printf '{"check_runs":[]}'
  fi
elif [[ "$*" == *'/health'* ]]; then
  printf '{"status":"ok","revision":"%s"}' "$MOCK_HEAD"
else exit 96; fi
MOCK
cat > "$bin/node" <<'MOCK'
#!/usr/bin/env bash
set -eu
if [[ "$1" == scripts/production-smoke.mjs ]]; then
  printf 'mock public smoke\n' >> "$MOCK_LOG"
  exit 0
fi
exec "$REAL_NODE" "$@"
MOCK
chmod 700 "$bin"/*
export MOCK_HEAD="$mock_head" MOCK_BASE="$mock_head" REAL_NODE="$real_node" MOCK_LOG="$log"
export PUBLIC_ORIGIN='https://pcb.example.test'
export OAUTH_ISSUER="$PUBLIC_ORIGIN/api/auth"
export OAUTH_JWKS_URL="$PUBLIC_ORIGIN/api/auth/jwks"
export OAUTH_AUDIENCE="$PUBLIC_ORIGIN/mcp"
export KICAD_DB_PASSWORD='synthetic-test-password'
export AUTH_MODE='builtin' BETTER_AUTH_SECRET='synthetic-auth-fixture-value-at-least-32-characters'
export GITHUB_CLIENT_ID='test-id' GITHUB_CLIENT_SECRET='synthetic-test-client-secret'
export KICAD_TUNNEL_NETWORK='pcb_dedicated_ingress'
export CLOUDFLARE_TUNNEL_TOKEN='synthetic-test-tunnel-token'
export KICAD_DOPPLER_SCOPED=true
unset DOPPLER_TOKEN DOPPLER_PROJECT DOPPLER_CONFIG || true
# The executable override exists only for this test subprocess, scoped to a
# mode-0700 temporary directory and deleted on EXIT.
export PATH="$bin:$PATH"
run_fixture() {
  local mode="$1"
  : > "$log"
  MOCK_EXISTING="$2" MOCK_CI_PASS="$3" bash scripts/bootstrap-production-vps.sh "$mode"
}
assert_no_mutation() {
  if grep -Eq 'docker (network create|build |compose .* (up|run))' "$log"; then
    echo 'FAIL: mocked preflight/CI failure attempted a mutation' >&2
    exit 1
  fi
}
output=$(run_fixture preflight '' no)
[[ "$output" == *'New VPS preflight passed'* ]]
assert_no_mutation
echo 'PASS: non-mutating new VPS preflight'
for existing in container volume edge; do
  if output=$(run_fixture preflight "$existing" no 2>&1); then
    echo 'FAIL: existing state was accepted' >&2
    exit 1
  fi
  [[ "$output" == *'Existing'*'detected'* ]]
  assert_no_mutation
  if grep -q 'doppler run' "$log"; then
    echo 'FAIL: secrets fetched despite existing production state' >&2
    exit 1
  fi
done
echo 'PASS: existing app/database safely rejected'
if output=$(run_fixture install '' no 2>&1); then
  echo 'FAIL: installation accepted an unverified CI revision' >&2
  exit 1
fi
[[ "$output" == *'CI proof unavailable'* ]]
assert_no_mutation
echo 'PASS: installation fails closed without exact-SHA CI proof'
output=$(run_fixture install '' yes)
[[ "$output" == *'Release timer NOT enabled'* ]]
grep -q 'docker network create --driver bridge pcb_dedicated_ingress' "$log"
grep -q 'migrations-cli.js --apply' "$log"
grep -q 'docker compose -f infra/compose.cloudflare.yml up -d cloudflared' "$log"
grep -q 'mock public smoke' "$log"
if grep -Eq 'systemctl|kicad-cloud-production.timer' "$log"; then
  echo 'FAIL: installer touched an existing release watcher' >&2
  exit 1
fi
echo 'PASS: fresh install provisions in isolation without enabling another release watcher'
# A detached, owner-reviewed PR checkout is allowed ONLY in the two explicitly
# named -pr modes; never in ordinary first-install modes.
export MOCK_HEAD='b189aeaadef23f226e6438d00655922484c46143'
export MOCK_BASE='1697bf37f689aac3f16eca2dc0b5827f055e9795'
: > "$log"
if output=$(MOCK_EXISTING='' MOCK_CI_PASS=yes bash scripts/bootstrap-production-vps.sh preflight 2>&1); then
  echo 'FAIL: ordinary production preflight accepted a PR checkout' >&2; exit 1
fi
[[ "$output" == *'locally verified current origin/main'* ]]
if output=$(MOCK_EXISTING='' MOCK_CI_PASS=no bash scripts/bootstrap-production-vps.sh preflight-pr 63 "$MOCK_HEAD" 2>&1); then
  echo 'FAIL: acceptance preflight accepted missing PR CI' >&2; exit 1
fi
[[ "$output" == *'acceptance blocked'* ]]
assert_no_mutation
output=$(MOCK_EXISTING='' MOCK_CI_PASS=yes bash scripts/bootstrap-production-vps.sh preflight-pr 63 "$MOCK_HEAD")
[[ "$output" == *'New VPS preflight passed'* ]]
assert_no_mutation
echo 'PASS: only reviewed, exact-head PR with all green scans can preflight'
: > "$log"
output=$(MOCK_EXISTING='' MOCK_CI_PASS=yes bash scripts/bootstrap-production-vps.sh install-pr 63 "$MOCK_HEAD")
[[ "$output" == *'PR #63'*"$MOCK_HEAD"* ]]
[[ "$output" == *'Release timer NOT enabled'* ]]
grep -q 'migrations-cli.js --apply' "$log"
echo 'PASS: isolated PR acceptance install requires security proof and leaves watcher OFF'


# CI/Security passing initially is not enough: the PR and main must still
# match after the OCI build and BEFORE database writes.
for scenario in pr main closed dirty; do
  : > "$log"
  export MOCK_ADVANCE_AFTER_BUILD='' MOCK_CLOSE_AFTER_BUILD='' MOCK_DIRTY_AFTER_BUILD=''
  case "$scenario" in
    pr|main) export MOCK_ADVANCE_AFTER_BUILD="$scenario";;
    closed) export MOCK_CLOSE_AFTER_BUILD=yes;;
    dirty) export MOCK_DIRTY_AFTER_BUILD=yes;;
  esac
  if out=$(MOCK_EXISTING='' MOCK_CI_PASS=yes bash scripts/bootstrap-production-vps.sh install-pr 63 "$MOCK_HEAD" 2>&1); then
    echo "FAIL: install accepted changed $scenario after build" >&2; exit 1
  fi
  case "$scenario" in
    pr) [[ "$out" == *'Reviewed PR head changed during installation'* ]];;
    main) [[ "$out" == *'Remote main advanced during installation'* ]];;
    closed) [[ "$out" == *'Reviewed PR closed or changed during installation'* ]];;
    dirty) [[ "$out" == *'Reviewed checkout changed during initial installation'* ]];;
  esac || { echo "FAIL: wrong rejection for $scenario: $out" >&2; exit 1; }
  grep -q '^docker build ' "$log"
  if grep -Eq 'docker (network create|compose.*up -d db)|migrations-cli.js --apply' "$log"; then
    echo "FAIL: $scenario change allocated an ingress network or started a database" >&2; exit 1
  fi
  echo "PASS: $scenario changed after build -> no database started"
done
unset MOCK_ADVANCE_AFTER_BUILD MOCK_CLOSE_AFTER_BUILD MOCK_DIRTY_AFTER_BUILD


# Even a valid CI-verified PR must refuse an in-flight Doppler credential
# rotation after the image has built and before any ingress/DB provisioning.
: > "$log"
if out=$(MOCK_EXISTING='' MOCK_CI_PASS=yes MOCK_DOPPLER_ROTATE_AFTER_BUILD=yes \
  bash scripts/bootstrap-production-vps.sh install-pr 63 "$MOCK_HEAD" 2>&1); then
  echo 'FAIL: install accepted changed Doppler settings after build' >&2
  exit 1
fi
[[ "$out" == *'Doppler configuration changed during image build'* ]]
grep -q '^docker build ' "$log"
if grep -Eq 'docker (network create|compose.*up -d db)|migrations-cli.js --apply' "$log"; then
  echo 'FAIL: changed Doppler config allocated network or database' >&2
  exit 1
fi
echo 'PASS: Doppler secret rotated after build -> no ingress network or database created'
