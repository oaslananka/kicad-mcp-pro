-- Draft-only issuer storage, not a public HTTP or credential-enrollment API.
-- Only a separately authenticated human-owner authority may insert active
-- passkeys. The production Cloud app does not connect to this issuer.
CREATE TABLE owner_read_passkeys (
  credential_id text PRIMARY KEY CHECK(length(credential_id) BETWEEN 24 AND 1024),
  owner_sub text NOT NULL CHECK(length(owner_sub) BETWEEN 1 AND 256),
  public_key bytea NOT NULL CHECK(octet_length(public_key) BETWEEN 32 AND 2048),
  sign_count bigint NOT NULL DEFAULT 0 CHECK(sign_count >= 0),
  enabled boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX owner_read_passkeys_owner ON owner_read_passkeys(owner_sub)
  WHERE enabled;

CREATE TABLE owner_read_webauthn_challenges (
  request_id uuid PRIMARY KEY,
  owner_sub text NOT NULL CHECK(length(owner_sub) BETWEEN 1 AND 256),
  client_id text NOT NULL CHECK(length(client_id) BETWEEN 1 AND 1024),
  device_id uuid NOT NULL,
  project_id uuid NOT NULL,
  cloud_origin text NOT NULL CHECK(length(cloud_origin) BETWEEN 9 AND 256
    AND cloud_origin LIKE 'https://%'),
  credential_id text NOT NULL REFERENCES owner_read_passkeys(credential_id),
  challenge_digest bytea NOT NULL UNIQUE CHECK(octet_length(challenge_digest) = 32),
  issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  CHECK(expires_at > issued_at AND expires_at <= issued_at + interval '30 seconds'),
  CHECK(used_at IS NULL OR used_at >= issued_at)
);
CREATE INDEX owner_read_webauthn_challenges_expiry
  ON owner_read_webauthn_challenges(expires_at);
