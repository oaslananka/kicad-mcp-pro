#!/usr/bin/env bash
# One encrypted production DB snapshot; does not create Docker images.
set -euo pipefail
umask 077

if [[ -z "$KICAD_BACKUP_AGE_IDENTITY" || -z "$KICAD_BACKUP_AGE_RECIPIENT" ]]; then
  echo "Production backup key and recipient required from Doppler" >&2
  exit 2
fi
for required_command in docker age age-keygen mktemp; do
  command -v "$required_command" >/dev/null || {
    echo "Backup prerequisite missing" >&2
    exit 2
  }
done

database_container="kicad-cloud-db-1"
if [[ "$(docker inspect "$database_container" --format '{{.State.Health.Status}}')" != "healthy" ]]; then
  echo "Production PostgreSQL is not healthy; aborting backup" >&2
  exit 1
fi
backup_dir="$HOME/.local/share/kicad-cloud/backups"
if [[ -L "$backup_dir" ]]; then
  echo "Refusing a symlink for production backup directory" >&2
  exit 1
fi
mkdir -p -m 700 -- "$backup_dir"
chmod 700 -- "$backup_dir"
key_dir="$(mktemp -d /dev/shm/kicad-cloud-key.XXXXXXXX)"
partial="$(mktemp "$backup_dir/.partial.XXXXXXXX")"
cleanup() {
  rm -f -- "$partial"
  rm -rf -- "$key_dir"
}
trap cleanup EXIT
printf '%s\n' "$KICAD_BACKUP_AGE_IDENTITY" > "$key_dir/identity"
chmod 600 "$key_dir/identity"
if [[ "$(age-keygen -y "$key_dir/identity")" != "$KICAD_BACKUP_AGE_RECIPIENT" ]]; then
  echo "Backup age identity does not match configured recipient" >&2
  exit 1
fi

# Streams database data directly into authenticated age encryption; no
# plaintext database dump touches disk or the production Docker volume.
docker exec -u postgres "$database_container" pg_dump \
  -U kicad_cloud -d kicad_cloud -Fc --no-owner --no-acl |
  age -r "$KICAD_BACKUP_AGE_RECIPIENT" > "$partial"
if [[ ! -s "$partial" ]]; then
  echo "Backup produced no encrypted data" >&2
  exit 1
fi
# Checks decryption and pg_restore's archive parser, not a complete restore.
age -d -i "$key_dir/identity" "$partial" |
  docker exec -i "$database_container" pg_restore --list >/dev/null
chmod 600 -- "$partial"
mv -f -- "$partial" "$backup_dir/production-db-latest.pg.age"
echo "Encrypted production DB snapshot verified and atomically replaced"
