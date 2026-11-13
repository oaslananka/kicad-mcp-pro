#!/usr/bin/env bash
# Identify precisely one healthy KiCad Cloud database, without Docker name guesses.
# Source this function in backup/restore scripts; it never changes database state.
kicad_cloud_database_container() {
  local listing candidate status database
  local -a matches=()
  listing="$(docker ps --filter 'label=coolify.type=database' \
    --filter 'label=coolify.projectName=kicad-mcp-cloud' \
    --filter 'label=coolify.resourceName=kicad-cloud-postgres' \
    --format '{{.Names}}')" || {
    echo 'Could not discover the Cloud production database' >&2
    return 1
  }
  while IFS= read -r candidate; do
    [[ -z "$candidate" ]] || matches+=("$candidate")
  done <<< "$listing"
  if docker container inspect kicad-cloud-db-1 >/dev/null 2>&1 &&
    [[ "$(docker inspect kicad-cloud-db-1 --format '{{.State.Running}}')" == true ]]; then
    matches+=(kicad-cloud-db-1)
  fi
  if [[ ${#matches[@]} -ne 1 ]]; then
    echo 'Expected exactly one KiCad Cloud production database' >&2
    return 1
  fi
  candidate="${matches[0]}"
  [[ "$candidate" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || {
    echo 'Invalid database container identity' >&2
    return 1
  }
  status="$(docker inspect "$candidate" --format '{{.State.Health.Status}}')" || return 1
  if [[ "$status" != healthy ]]; then
    echo 'KiCad Cloud production database is not healthy' >&2
    return 1
  fi
  database="$(docker exec "$candidate" sh -c \
    'test "$POSTGRES_DB" = kicad_cloud && psql -X -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT current_database()"')" || return 1
  if [[ "$database" != kicad_cloud ]]; then
    echo 'Discovered container is not the KiCad Cloud production database' >&2
    return 1
  fi
  printf '%s\n' "$candidate"
}
