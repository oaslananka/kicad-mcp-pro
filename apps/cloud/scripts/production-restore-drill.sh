#!/usr/bin/env bash
# Operator-only full, encrypted production backup restore to disposable PG17.
# Does NOT modify production DB, networks, application image or tunnel.
set -euo pipefail
umask 077

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--rehearse-schema" ) ]]; then
  echo 'Usage: doppler run -p kicad-mcp-pro -c prd_cloud -- bash scripts/production-restore-drill.sh [--rehearse-schema]' >&2
  exit 2
fi
rehearse_schema=false
if [[ "${1:-}" == "--rehearse-schema" ]]; then rehearse_schema=true; fi
for needed in docker age age-keygen mktemp openssl; do
  command -v "$needed" >/dev/null || { echo 'Restore drill prerequisite unavailable' >&2; exit 2; }
done
if [[ -z "${KICAD_BACKUP_AGE_IDENTITY:-}" || -z "${KICAD_BACKUP_AGE_RECIPIENT:-}" ]]; then
  echo 'Authorized production backup key/recipient unavailable' >&2
  exit 2
fi

BACKUP="$HOME/.local/share/kicad-cloud/backups/production-db-latest.pg.age"
[[ -f "$BACKUP" && ! -L "$BACKUP" && -s "$BACKUP" ]] || {
  echo 'Encrypted production backup not present as a regular nonempty file' >&2
  exit 2
}
# Strict fail closed on readable-by-others backup and symlinked parent.
if [[ -L "$(dirname "$BACKUP")" ]]; then
  echo 'Refusing symlinked backup directory' >&2
  exit 2
fi
backup_mode="$(stat -c '%a' "$BACKUP")"
if (( 8#$backup_mode & 077 )); then
  echo 'Encrypted backup permissions are too broad' >&2
  exit 2
fi
source "$(dirname "${BASH_SOURCE[0]}")/production-db-target.sh"
source_db="$(kicad_cloud_database_container)"
suffix="$(openssl rand -hex 8)"
network="kicad-restore-drill-$suffix"
target="kicad-restore-pg-$suffix"
tmp_dir="$(mktemp -d /dev/shm/kicad-restore-key.XXXXXXXX)"
cleanup(){
  docker rm -f "$target" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  rm -rf -- "$tmp_dir"
}
trap cleanup EXIT
printf '%s\n' "$KICAD_BACKUP_AGE_IDENTITY" > "$tmp_dir/identity"
chmod 600 "$tmp_dir/identity"
[[ "$(age-keygen -y "$tmp_dir/identity")" == "$KICAD_BACKUP_AGE_RECIPIENT" ]] || {
  echo 'Backup identity/recipient mismatch' >&2
  exit 1
}

fixture_pass="$(openssl rand -hex 24)"
docker network create --internal "$network" >/dev/null
# All decrypted customer metadata remains in disposable TMPFS, not host
# overlay volumes/disk. No production volume or published TCP port.
docker run --rm -d \
  --name "$target" --network "$network" \
  --tmpfs /var/lib/postgresql/data:rw,size=128m \
  --tmpfs /var/run/postgresql:rw,size=16m \
  --tmpfs /tmp:rw,size=16m \
  -e POSTGRES_USER=restore_fixture \
  -e POSTGRES_DB=restore_fixture \
  -e "POSTGRES_PASSWORD=$fixture_pass" \
  postgres:17-alpine >/dev/null
ready=false
for _ in {1..35}; do
  if docker exec "$target" pg_isready -q -U restore_fixture -d restore_fixture; then
    ready=true
    break
  fi
  sleep 1
done
[[ "$ready" == true ]] || { echo 'Isolated PostgreSQL unavailable'; exit 1; }

# Read authenticated age archive from private disk; decrypted bytes flow
# directly via pipe into PostgreSQL in RAM. Never write plaintext dump.
age -d -i "$tmp_dir/identity" "$BACKUP" |
 docker exec -i "$target" pg_restore \
  --exit-on-error --no-owner --no-acl \
  -U restore_fixture -d restore_fixture >/dev/null
query_target(){
  docker exec "$target" psql -X -q -A -t \
    -v ON_ERROR_STOP=1 -U restore_fixture -d restore_fixture -c "$1"
}
query_live(){
  docker exec "$source_db" sh -c \
    'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' \
    sh "$1"
}
ledger_query="SELECT count(*)::text || ':' || coalesce(md5(string_agg(version::text || ':' || checksum, '|' ORDER BY version)), '') FROM schema_migrations"
restored_ledger="$(query_target "$ledger_query")"
live_ledger="$(query_live "$ledger_query")"
[[ "$restored_ledger" == "$live_ledger" ]] || {
  echo 'Live and restored schema migration ledgers differ (fresh snapshot required)' >&2
  exit 1
}
# Additional read-only checks for restored full schema and security fences.
for q in \
  'SELECT count(*) FROM devices' \
  'SELECT count(*) FROM projects' \
  'SELECT count(*) FROM project_client_grants' \
  'SELECT count(*) FROM "users"' \
  'SELECT count(*) FROM "oauthClient"' \
  'SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname IN ('\''kicad_fence_refresh_insert'\'','\''kicad_fence_opaque_access_insert'\'','\''kicad_fence_refresh_replay'\'')'
do
  [[ "$(query_live "$q")" == "$(query_target "$q")" ]] || {
    echo 'Full restore validation failed: security/metadata count mismatch' >&2
    exit 1
  }
done

echo 'PASS: encrypted live Cloud backup fully restored to isolated, disposable PostgreSQL 17 RAM; schema ledger, security triggers and metadata counts match production'
if [[ "$rehearse_schema" == true ]]; then
  # Same checksum-aware migration runner as production, but on the RAM-only
  # cloned database. Never grant the test container a production DB URL.
  for needed in node; do
    command -v "$needed" >/dev/null || {
      echo 'Migration rehearsal prerequisite unavailable' >&2; exit 2;
    }
  done
  [[ -f dist/migrations-cli.js && -f dist/migrations.js &&
     -f db/001_inventory.pgsql ]] || {
    echo 'Reviewed migration build or SQL directory unavailable' >&2
    exit 2
  }
  test_image="${KICAD_CLOUD_RESTORE_TEST_IMAGE:-kicad-mcp-pro-cloud:production}"
  docker image inspect "$test_image" >/dev/null || {
    echo 'Existing reviewed migration runtime image unavailable' >&2
    exit 2
  }
  run_migration() {
    local action="$1"
    docker run --rm --network "$network" --read-only --pids-limit 64 \
      --memory 384m --entrypoint node \
      --mount "type=bind,src=$PWD,dst=/app/workspace,readonly" \
      --workdir /app/workspace \
      -e "DATABASE_URL=postgresql://restore_fixture:$fixture_pass@$target:5432/restore_fixture" \
      "$test_image" /app/workspace/dist/migrations-cli.js "$action"
  }
  source_version="$(query_live 'SELECT coalesce(max(version),0) FROM schema_migrations')"
  [[ "$source_version" =~ ^[0-9]+$ ]] || {
    echo 'Invalid source migration history' >&2; exit 1
  }
  latest_version="$(node --input-type=module -e \
    "import {migrationFiles} from './dist/migrations.js';process.stdout.write(String(migrationFiles.length))")"
  [[ "$latest_version" =~ ^[0-9]+$ &&
     "$latest_version" -ge "$source_version" ]] || {
    echo 'Reviewed migration manifest is behind the live schema' >&2; exit 1
  }
  before="$(run_migration --status)"
  [[ "$before" == *"\"current\":$source_version"* ]] || {
    echo 'Restored snapshot migration history differs from the reviewed runner' >&2
    exit 1
  }
  original_grants="$(query_target 'SELECT count(*)::text || chr(58) || count(*) FILTER (WHERE enabled) FROM connector_managed_read_access')"
  run_migration --apply >/dev/null
  after="$(run_migration --status)"
  [[ "$after" == *'"pending":[]'* && "$after" == *"\"current\":$latest_version"* ]] || {
    echo 'Migrated clone did not reach the reviewed schema version' >&2; exit 1
  }
  [[ "$(run_migration --apply)" == "$after" ]] || {
    echo 'Migrated clone did not apply idempotently' >&2; exit 1
  }
  [[ "$original_grants" == "$(query_target 'SELECT count(*)::text || chr(58) || count(*) FILTER (WHERE enabled) FROM connector_managed_read_access')" ]] || {
    echo 'Existing managed project access changed during clone migration' >&2
    exit 1
  }
  if (( latest_version >= 20 )); then
    [[ "$(query_target "SELECT to_regclass('connector_write_proof_reservations') IS NOT NULL")" == t ]] || {
      echo 'Write proof reservation table missing from clone' >&2; exit 1
    }
  fi
  if (( latest_version >= 21 )); then
    [[ "$(query_target 'SELECT count(*) FROM connector_managed_read_access WHERE cardinality(native_operations)>0')" == 0 &&
       "$(query_target "SELECT count(*) FROM pg_constraint WHERE conname='managed_native_read_operations_allowlist'")" == 1 ]] || {
      echo 'Native operation permissions are unexpectedly enabled or unconstrained' >&2
      exit 1
    }
  fi
  for q in 'SELECT count(*) FROM devices' \
    'SELECT count(*) FROM projects' \
    'SELECT count(*) FROM project_client_grants' \
    'SELECT count(*) FROM "users"' \
    'SELECT count(*) FROM "oauthClient"'; do
    [[ "$(query_live "$q")" == "$(query_target "$q")" ]] || {
      echo 'Existing metadata count changed during clone migration' >&2; exit 1
    }
  done
  [[ "$(query_live 'SELECT max(version) FROM schema_migrations')" == "$source_version" ]] || {
    echo 'Live source schema changed during the rehearsal' >&2; exit 1
  }
  printf 'PASS: full backup clone migrated %s to %s with checked history, empty native grants, stable metadata and idempotent reapply\n' \
    "$source_version" "$latest_version"
fi
