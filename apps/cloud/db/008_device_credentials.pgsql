-- Revocable, public-key-only device enrollment. No credential secret is stored.
-- Enrollment transaction MUST update the challenge and insert both rows atomically.
CREATE TABLE device_credentials (
  device_id uuid PRIMARY KEY,
  owner_sub text NOT NULL,
  public_key_der text NOT NULL CHECK (length(public_key_der) BETWEEN 32 AND 192),
  key_fingerprint char(64) NOT NULL UNIQUE
    CHECK (key_fingerprint ~ '^[0-9a-f]{64}$'),
  pairing_challenge_id uuid NOT NULL UNIQUE
    REFERENCES pairing_challenges(id) ON DELETE RESTRICT,
  issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  revoked_at timestamptz,
  FOREIGN KEY (device_id, owner_sub) REFERENCES devices(id, owner_sub) ON DELETE CASCADE,
  CHECK (revoked_at IS NULL OR revoked_at >= issued_at)
);
CREATE INDEX device_credentials_owner ON device_credentials(owner_sub, device_id);
