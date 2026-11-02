#!/usr/bin/env bash
# Disposable PostgreSQL 17 backup/restore acceptance, never a production tool.
set -euo pipefail

if [[ $# -ne 1 || -z "$1" ]]; then
  echo 'Usage: ci-db-restore-drill.sh <already-built-test-image>' >&2
  exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
  echo 'Docker is required for the isolated restore drill' >&2
  exit 2
fi
image=$1
docker image inspect "$image" >/dev/null
suffix="$(openssl rand -hex 7)"
# Generated for disposable test containers only. Never persisted or logged.
fixture_password="$(openssl rand -hex 24)"
network="kicad-drill-$suffix"
source="kicad-drill-source-$suffix"
target="kicad-drill-target-$suffix"
cleanup() {
  docker rm -f "$source" "$target" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create --internal "$network" >/dev/null
for name in "$source" "$target"; do
  # Fixture-only credentials: no Doppler data and no published host ports.
  docker run --rm -d --name "$name" --network "$network" \
    --network-alias "$name" \
    -e POSTGRES_USER=fixture -e "POSTGRES_PASSWORD=$fixture_password" \
    -e POSTGRES_DB=cloud_fixture postgres:17-alpine >/dev/null
  attempts=0
  until docker exec "$name" pg_isready -q -U fixture -d cloud_fixture; do
    attempts=$((attempts+1))
    if ((attempts>=35)); then
      echo 'Temporary PostgreSQL fixture failed to become ready' >&2
      exit 1
    fi
    sleep 1
  done
done

cli() {
  local database_host=$1 action=$2
  docker run --rm --network "$network" \
    -e "DATABASE_URL=postgresql://fixture:$fixture_password@$database_host:5432/cloud_fixture" \
    "$image" node dist/migrations-cli.js "$action"
}
sql() {
  local database_host=$1 query=$2
  docker exec "$database_host" psql -X -v ON_ERROR_STOP=1 -q -t -A \
    -U fixture -d cloud_fixture -c "$query"
}
assert_eq() {
  local actual=$1 expected=$2 description=$3
  if [[ "$actual" != "$expected" ]]; then
    printf 'Restore drill FAILED: %s (expected %s, got %s)\n' \
      "$description" "$expected" "$actual" >&2
    exit 1
  fi
}
echo 'Restore drill: applying reviewed database schema in source fixture'
cli "$source" --status >/dev/null
cli "$source" --apply >/dev/null
assert_eq "$(sql "$source" 'SELECT count(*) FROM schema_migrations')" "18" "source migration count"

# Only synthetic metadata; no physical KiCad paths, files or user credentials.
sql "$source" "INSERT INTO devices(id,owner_sub,alias,enabled) VALUES
  ('c3e0d32d-d8bf-49c8-ae15-f2acc4c147b7','fixture-owner','Fixture Device',true)" >/dev/null
sql "$source" "INSERT INTO projects(id,owner_sub,device_id,alias,enabled)
  VALUES('a39a9f88-d390-4431-8cd4-2c4430aad321','fixture-owner',
  'c3e0d32d-d8bf-49c8-ae15-f2acc4c147b7','Fixture Project',true)" >/dev/null
sql "$source" "INSERT INTO project_client_grants(project_id,owner_sub,client_id,enabled,max_mode)
  VALUES('a39a9f88-d390-4431-8cd4-2c4430aad321','fixture-owner','fixture-client',true,'readonly')" >/dev/null
sql "$source" "INSERT INTO client_token_cutoffs(owner_sub,client_id,revoked_at)
  VALUES('fixture-owner','fixture-client','2026-10-01T00:00:00Z')" >/dev/null
sql "$source" "INSERT INTO \"users\"(\"id\",\"name\",\"email\",\"emailVerified\",\"createdAt\",\"updatedAt\")
  VALUES('fixture-owner','Test Owner','synthetic@example.invalid',true,now(),now())" >/dev/null
sql "$source" "INSERT INTO \"oauthClient\"(\"id\",\"clientId\",\"redirectUris\")
  VALUES('fixture-client-row','fixture-client','[]'::jsonb)" >/dev/null

# Synthetic metadata only; never a real device credential.
sql "$source" "INSERT INTO pairing_challenges
  (id,device_alias,device_public_key_der,device_fingerprint,user_code_mac,device_code_mac,expires_at,state,owner_sub)
  VALUES ('d83484f3-5515-46a5-96dd-3b92b73721c0','Fixture KiCad',
    repeat('A',64),repeat('a',64),repeat('b',64),repeat('c',64),
    clock_timestamp() + interval '4 minutes','consumed','fixture-owner')" >/dev/null

# Synthetic revocable public-key identity, never a real private credential.
sql "$source" "INSERT INTO device_credentials
  (device_id,owner_sub,public_key_der,key_fingerprint,pairing_challenge_id)
  VALUES ('c3e0d32d-d8bf-49c8-ae15-f2acc4c147b7','fixture-owner',
    repeat('A',64),repeat('a',64),
    'd83484f3-5515-46a5-96dd-3b92b73721c0')" >/dev/null

# Synthetic pending nonce DIGEST only; neither a real nonce nor a signing key.
sql "$source" "INSERT INTO device_handshake_challenges
  (id,device_id,owner_sub,nonce_sha256,created_at,expires_at)
  VALUES('41763f41-bebb-476c-a18a-58d303841e91',
    'c3e0d32d-d8bf-49c8-ae15-f2acc4c147b7',
    'fixture-owner',repeat('d',64),clock_timestamp(),
    clock_timestamp() + interval '45 seconds')" >/dev/null

# Synthetic session metadata only; never a real connection binding or bearer token.
sql "$source" "INSERT INTO connector_sessions
  (id,device_id,owner_sub,handshake_id,connection_digest,created_at,expires_at)
  VALUES ('17bcf345-4d7f-43f1-b2d6-ed6ee2418a6e',
    'c3e0d32d-d8bf-49c8-ae15-f2acc4c147b7','fixture-owner',
    '41763f41-bebb-476c-a18a-58d303841e91',
    repeat('e',64),clock_timestamp(),clock_timestamp()+interval '3 minutes')" >/dev/null

# Synthetic owner-scoped budget (no pairing user code or device secret).
sql "$source" "INSERT INTO pairing_review_budget(owner_sub,window_started_at,attempts)
 VALUES('fixture-owner',clock_timestamp(),3)" >/dev/null

# Synthetic keyed rate budget only (no raw source address or device identifier).
sql "$source" "INSERT INTO pairing_device_budget(budget_key,window_started_at,attempts)
 VALUES(repeat('f',64),clock_timestamp(),4)" >/dev/null

# Synthetic CONSUMED approval metadata only. A restored row must never
# become a new reusable grant, including if a backup is restored elsewhere.
sql "$source" "INSERT INTO owner_read_approvals
  (request_id,owner_sub,client_id,device_id,project_id,cloud_origin,
   operation,issued_at,expires_at,consumed_at)
  VALUES ('f41d811b-7d84-4d5e-8335-387b4e94f1c5','fixture-owner','fixture-client',
    'c3e0d32d-d8bf-49c8-ae15-f2acc4c147b7',
    'a39a9f88-d390-4431-8cd4-2c4430aad321',
    'https://fixture.example.invalid','project_summary',
    now(),now()+interval '20 seconds',now())" >/dev/null

echo 'Restore drill: streaming PostgreSQL custom backup to fresh target'
docker exec "$source" pg_dump -Fc -U fixture -d cloud_fixture \
  --no-owner --no-acl |
  docker exec -i "$target" pg_restore -U fixture -d cloud_fixture \
    --no-owner --no-acl --exit-on-error

echo 'Restore drill: checking migrations, permissions and authorization fences'
cli "$target" --status >/dev/null
cli "$target" --apply >/dev/null
assert_eq "$(sql "$target" 'SELECT count(*) FROM schema_migrations')" "18" "restored migration ledger"
assert_eq "$(sql "$target" "SELECT count(*) FROM devices WHERE owner_sub='fixture-owner'")" "1" "device metadata"
assert_eq "$(sql "$target" "SELECT count(*) FROM projects WHERE owner_sub='fixture-owner'")" "1" "project metadata"
assert_eq "$(sql "$target" "SELECT count(*) FROM project_client_grants WHERE owner_sub='fixture-owner' AND client_id='fixture-client' AND enabled")" "1" "client grant metadata"
assert_eq "$(sql "$target" "SELECT kicad_oauth_lineage_blocked('fixture-owner','fixture-client','old-code')")" "t" "token issuance cutoff"
assert_eq "$(sql "$target" "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname IN ('kicad_fence_refresh_insert','kicad_fence_opaque_access_insert','kicad_fence_refresh_replay')")" "3" "restored OAuth triggers"
# Verify actual trigger rejection, not merely function/table presence. This
# synthetic token INSERT MUST raise SQLSTATE 23514 due to restored cutoff.
sql "$target" "DO \$do\$
BEGIN
  INSERT INTO \"oauthRefreshToken\"(\"id\",\"token\",\"clientId\",\"userId\",\"scopes\",\"createdAt\",\"expiresAt\",\"authorizationCodeId\")
  VALUES('denied-token','denied-token-hash','fixture-client','fixture-owner',
    '[]'::jsonb,now(),now() + interval '1 hour','old-code');
  RAISE EXCEPTION 'late token was incorrectly accepted';
EXCEPTION WHEN SQLSTATE '23514' THEN NULL;
END \$do\$" >/dev/null
assert_eq "$(sql "$target" 'SELECT count(*) FROM "oauthRefreshToken"')" "0" "rejected token was not inserted"
source_ledger="$(sql "$source" "SELECT md5(string_agg(version || ':' || checksum, '|' ORDER BY version)) FROM schema_migrations")"
target_ledger="$(sql "$target" "SELECT md5(string_agg(version || ':' || checksum, '|' ORDER BY version)) FROM schema_migrations")"
assert_eq "$(sql "$target" 'SELECT count(*) FROM pairing_challenges')" "1" "restored pairing metadata"
assert_eq "$(sql "$target" "SELECT attempts FROM pairing_review_budget WHERE owner_sub='fixture-owner'")" "3" "restored pairing review budget"
assert_eq "$(sql "$target" "SELECT attempts FROM pairing_device_budget WHERE budget_key=repeat('f',64)")" "4" "restored device pairing budget"
assert_eq "$(sql "$target" 'SELECT count(*) FROM device_credentials WHERE revoked_at IS NULL')" "1" "restored public-key device credential"
assert_eq "$(sql "$target" 'SELECT count(*) FROM device_handshake_challenges')" "1" "restored handshake challenge"
assert_eq "$(sql "$target" 'SELECT count(*) FROM connector_sessions')" "1" "restored connector session"
assert_eq "$(sql "$target" "SELECT count(*) FROM owner_read_approvals
  WHERE request_id='f41d811b-7d84-4d5e-8335-387b4e94f1c5'
  AND consumed_at IS NOT NULL")" "1" "restored approval remains consumed"
assert_eq "$(sql "$target" "SELECT state FROM connector_sessions WHERE id='17bcf345-4d7f-43f1-b2d6-ed6ee2418a6e'")" "pending" "restored pending session"
assert_eq "$(sql "$target" "SELECT status FROM device_handshake_challenges WHERE id='41763f41-bebb-476c-a18a-58d303841e91'")" "pending" "handshake remains pending"
assert_eq "$(sql "$target" "SELECT count(*) FROM device_credentials WHERE owner_sub='fixture-owner' AND device_id IN (SELECT id FROM devices WHERE owner_sub='fixture-owner')")" "1" "credential ownership"
assert_eq "$target_ledger" "$source_ledger" "restored checksum ledger"
echo 'Restore drill passed: all thirteen migrations, owner receipt ledger, pairing metadata, cutoff policy and triggers recovered'
