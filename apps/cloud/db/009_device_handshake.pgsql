-- Independent, ephemeral proof-of-possession nonce; no connection token or grants.
CREATE TABLE device_handshake_challenges (
  id uuid PRIMARY KEY,
  device_id uuid NOT NULL,
  owner_sub text NOT NULL CHECK(length(owner_sub) BETWEEN 1 AND 256),
  nonce_sha256 char(64) NOT NULL UNIQUE CHECK(nonce_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending','verified','expired','failed','revoked')),
  failures smallint NOT NULL DEFAULT 0 CHECK(failures BETWEEN 0 AND 5),
  FOREIGN KEY(device_id,owner_sub) REFERENCES devices(id,owner_sub) ON DELETE CASCADE,
  CHECK(expires_at > created_at AND expires_at <= created_at + interval '60 seconds'),
  CHECK(status <> 'failed' OR failures = 5)
);
-- One active handshake per device across all Cloud workers.
CREATE UNIQUE INDEX device_handshake_pending_device
  ON device_handshake_challenges(device_id) WHERE status='pending';
CREATE INDEX device_handshake_expiry ON device_handshake_challenges(expires_at);
