#!/usr/bin/env bash
# Run only in the dedicated, clean KiCad Cloud production Git worktree.
# Outbound GitHub polling; no public deploy webhook, SSH port or new secret.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$root"
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/kicad-cloud-production.lock"
flock -n 9 || { echo 'Previous deployment still active; skipping'; exit 0; }

[[ -z "$(git status --porcelain)" ]] || { echo 'Dirty deployment checkout; refusing'; exit 1; }
[[ $(git remote get-url origin) == 'https://github.com/oaslananka/kicad-mcp-pro-cloud.git' ]] || {
  echo 'Unexpected repository remote'; exit 1;
}

target=$(git ls-remote origin refs/heads/main | awk '{print $1}')
[[ $target =~ ^[a-f0-9]{40}$ ]] || { echo 'Main SHA unavailable'; exit 1; }
public_origin=$(scripts/doppler-runtime.sh node scripts/portable-config.mjs origin)
expected_google=$(scripts/doppler-runtime.sh node scripts/portable-config.mjs google)
current=$(curl --fail --silent --show-error --max-time 10 \
  "$public_origin/health" | \
  python3 -c 'import json,sys; print(json.load(sys.stdin).get("revision","unknown"))' || echo unavailable)
[[ "$current" == "$target" ]] && { echo "Already deployed $target"; exit 0; }

# Public metadata API, called only when main differs; cannot deploy PR runs.
ci=$(curl --fail --silent --show-error --max-time 15 \
  --header 'Accept: application/vnd.github+json' \
  'https://api.github.com/repos/oaslananka/kicad-mcp-pro-cloud/actions/workflows/ci.yml/runs?branch=main&event=push&per_page=10')
verified=$(python3 -c '
import json,sys
sha=sys.argv[1]
try:
 runs=json.load(sys.stdin)["workflow_runs"]
except (KeyError,ValueError):
 sys.exit(2)
found=[r for r in runs if r.get("head_sha")==sha and r.get("event")=="push"]
print("yes" if any(r.get("status")=="completed" and r.get("conclusion")=="success" for r in found) else "no")
' "$target" <<< "$ci")
[[ "$verified" == yes ]] || { echo "Current main $target has no successful CI yet; not deploying"; exit 0; }

git fetch --no-tags --quiet origin main
[[ $(git rev-parse FETCH_HEAD) == "$target" ]] || { echo 'Main advanced during verification'; exit 0; }
git switch --detach --quiet "$target"
[[ -z "$(git status --porcelain)" ]] || { echo 'Deployment worktree changed unexpectedly'; exit 1; }
[[ $(git ls-remote origin refs/heads/main | awk '{print $1}') == "$target" ]] || {
  echo 'Main advanced before building; let next cycle handle it'; exit 0;
}

# Preserve the accepted ingress network on every future deployment
# and on rollback; never silently put an isolated app on ops_internal.
source scripts/production-compose-files.sh
select_production_compose_files
current_isolated=$(docker inspect kicad-cloud-app-1   --format '{{if index .NetworkSettings.Networks "kicad_cloud_ingress_private"}}yes{{else}}no{{end}}')
if [[ "$current_isolated" == yes && "${KICAD_CLOUD_PRODUCTION_INGRESS:-shared}" != isolated ]]; then
  echo "Live Cloud uses isolated ingress but deploy mode is not isolated; refusing" >&2
  exit 1
fi
# Validate before tagging or restarting any production image.
scripts/doppler-runtime.sh docker compose "${production_compose_files[@]}" config -q

old=$(docker image inspect kicad-mcp-pro-cloud:production --format '{{.Id}}')
running=$(docker inspect kicad-cloud-app-1 --format '{{.Image}}')
[[ "$old" == "$running" ]] || { echo 'Production tag and active container differ'; exit 1; }
previous_rollback=$(docker image inspect kicad-mcp-pro-cloud:rollback --format '{{.Id}}' 2>/dev/null || true)
docker build --pull=false --build-arg "APP_REVISION=$target" \
  -t kicad-mcp-pro-cloud:candidate .
[[ $(git ls-remote origin refs/heads/main | awk '{print $1}') == "$target" ]] || {
  echo 'Main advanced before deployment; candidate left for safe cleanup'; exit 0;
}
restore() {
  echo 'Deployment verification failed. Restoring previous application image.' >&2
  docker image tag "$old" kicad-mcp-pro-cloud:production
  scripts/doppler-runtime.sh \
    docker compose "${production_compose_files[@]}" up -d --no-deps --force-recreate app
}
docker image tag "$old" kicad-mcp-pro-cloud:rollback
docker image tag kicad-mcp-pro-cloud:candidate kicad-mcp-pro-cloud:production
if ! scripts/doppler-runtime.sh \
  docker compose "${production_compose_files[@]}" up -d --no-deps --force-recreate app; then
  restore; exit 1
fi
healthy=false
for attempt in $(seq 1 25); do
  status=$(docker inspect kicad-cloud-app-1 --format '{{.State.Health.Status}}')
  if [[ "$status" == healthy ]]; then healthy=true; break; fi
  echo "Waiting for app health ($attempt/25): $status"
  sleep 3
done
if [[ "$healthy" != true ]] || ! PUBLIC_ORIGIN="$public_origin" EXPECTED_GOOGLE_OAUTH="$expected_google" EXPECTED_REVISION="$target" node scripts/production-smoke.mjs; then
  restore; exit 1
fi
# Keep only active + one rollback tag; never prune unrelated applications.
docker image rm kicad-mcp-pro-cloud:candidate >/dev/null || true
if [[ -n "$previous_rollback" && "$previous_rollback" != "$old" ]]; then
  docker image rm "$previous_rollback" >/dev/null || true
fi
echo "Successfully deployed and verified $target"
