#!/usr/bin/env bash
# Run on a SECOND, operator-controlled machine containing only the encrypted
# archive. Identity is injected from the external secret manager on that host.
# No production connection, Docker network, plaintext dump or host volume.
set -euo pipefail
umask 077
if [[ $# -ne 1 ]]; then
  echo 'Usage: EXPECTED_SHA256=<digest> EXPECTED_SCHEMA_VERSION=<reviewed-version> doppler run -p kicad-mcp-pro -c prd_cloud -- bash scripts/offsite-restore-verify.sh /private/backup.pg.age' >&2
  exit 2
fi
archive="$1"
[[ -f "$archive" && -s "$archive" && ! -L "$archive" ]] || {
  echo 'Encrypted offsite archive is missing, empty or linked' >&2; exit 2;
}
[[ ! -L "$(dirname "$archive")" ]] || { echo 'Refusing linked archive directory' >&2; exit 2; }
mode=$(stat -c '%a' "$archive")
(( (8#$mode & 077) == 0 )) || { echo 'Offsite archive is readable by others' >&2; exit 2; }
[[ "${EXPECTED_SHA256:-}" =~ ^[a-f0-9]{64}$ ]] || { echo 'Expected encrypted archive SHA-256 required' >&2; exit 2; }
[[ "$(sha256sum "$archive" | awk '{print $1}')" == "$EXPECTED_SHA256" ]] || {
  echo 'Encrypted offsite archive differs from source receipt' >&2; exit 1;
}
[[ "${EXPECTED_SCHEMA_VERSION:-}" =~ ^[1-9][0-9]{0,2}$ ]] || {
  echo 'Expected positive reviewed schema version required' >&2; exit 2;
}
[[ "${EXPECTED_LEDGER:-}" =~ ^[1-9][0-9]*:[a-f0-9]{32}$ &&
    "${EXPECTED_LEDGER%%:*}" == "$EXPECTED_SCHEMA_VERSION" ]] || {
  echo 'Source migration checksum receipt/count must match schema version' >&2; exit 2;
}
[[ -n "${KICAD_BACKUP_AGE_IDENTITY:-}" && -n "${KICAD_BACKUP_AGE_RECIPIENT:-}" ]] || {
  echo 'Independent operator must provide authorized age identity through secret manager' >&2; exit 2;
}
for cmd in docker age age-keygen openssl mktemp; do command -v "$cmd" >/dev/null || { echo "Missing restore tool: $cmd" >&2; exit 2; }; done
[[ -d /dev/shm ]] || { echo 'RAM-only key staging unavailable' >&2; exit 2; }
tmp=$(mktemp -d /dev/shm/kicad-offsite-recovery.XXXXXXXX)
target="kicad-offsite-restore-$(openssl rand -hex 6)"
cleanup(){ docker rm -f "$target" >/dev/null 2>&1 || true; rm -rf -- "$tmp"; }
trap cleanup EXIT
printf '%s\n' "$KICAD_BACKUP_AGE_IDENTITY" > "$tmp/identity"
chmod 600 "$tmp/identity"
[[ "$(age-keygen -y "$tmp/identity")" == "$KICAD_BACKUP_AGE_RECIPIENT" ]] || {
  echo 'Independent recovery identity/recipient mismatch' >&2; exit 1;
}
password=$(openssl rand -hex 24)
docker run --rm -d --network none --name "$target" \
  --tmpfs /var/lib/postgresql/data:rw,size=256m \
  --tmpfs /var/run/postgresql:rw,size=16m \
  --tmpfs /tmp:rw,size=16m \
  -e POSTGRES_USER=offsite_fixture -e POSTGRES_DB=offsite_fixture \
  -e "POSTGRES_PASSWORD=$password" postgres:17-alpine >/dev/null
# Docker represents --tmpfs in HostConfig.Tmpfs rather than .Mounts.
[[ $(docker inspect "$target" --format '{{index .HostConfig.Tmpfs "/var/lib/postgresql/data"}}') == *size=256m* ]] || {
  echo 'Temporary database is not RAM-backed; refusing decryption' >&2; exit 1;
}
ready=false
for _ in $(seq 1 45); do
  # pg_isready alone is insufficient: the image bootstraps a temporary PG
  # server, shuts it down and starts the actual server.
  if docker logs "$target" 2>&1 | grep -q 'PostgreSQL init process complete; ready for start up' && \
      docker exec "$target" pg_isready -q -U offsite_fixture -d offsite_fixture; then
    ready=true; break
  fi
  sleep 1
done
[[ "$ready" == true ]] || { echo 'PostgreSQL final boot was not confirmed' >&2; exit 1; }
# No plaintext archive or password is written to any durable volume.
age -d -i "$tmp/identity" "$archive" |
  docker exec -i "$target" pg_restore --exit-on-error --no-owner --no-acl \
    -U offsite_fixture -d offsite_fixture >/dev/null
query(){ docker exec "$target" psql -X -A -t -q -v ON_ERROR_STOP=1 \
  -U offsite_fixture -d offsite_fixture -c "$1"; }
version=$(query 'SELECT max(version) FROM schema_migrations')
[[ "$version" == "$EXPECTED_SCHEMA_VERSION" ]] || { echo 'Recovered schema version differs' >&2; exit 1; }
ledger=$(query "SELECT count(*)::text || ':' || coalesce(md5(string_agg(version::text || ':' || checksum, '|' ORDER BY version)), '') FROM schema_migrations")
if [[ "$ledger" != "$EXPECTED_LEDGER" ]]; then
  echo 'Recovered migration checksums differ from signed-off source receipt' >&2; exit 1
fi
triggers=$(query "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname IN ('kicad_fence_refresh_insert','kicad_fence_opaque_access_insert','kicad_fence_refresh_replay')")
[[ "$triggers" == 3 ]] || { echo 'OAuth security fences absent from restore' >&2; exit 1; }
for table in devices projects project_client_grants '"users"' '"oauthClient"' '"oauthConsent"'; do
  count=$(query "SELECT count(*) FROM $table")
  [[ "$count" =~ ^[0-9]+$ ]] || { echo 'Metadata table unreadable after restore' >&2; exit 1; }
done
printf 'PASS: offsite encrypted restore, RAM-only isolated PG17, schema %s, ledger %s, OAuth fences %s\n' "$version" "$ledger" "$triggers"
