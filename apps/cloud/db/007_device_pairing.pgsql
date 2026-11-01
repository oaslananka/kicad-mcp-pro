-- Metadata-only, unexposed pairing challenges. Credentials and native paths never stored.
CREATE TABLE pairing_challenges (
  id uuid PRIMARY KEY,
  device_alias text NOT NULL CHECK (length(device_alias) BETWEEN 1 AND 64),
  device_public_key_der text NOT NULL CHECK (length(device_public_key_der) BETWEEN 32 AND 192),
  device_fingerprint char(64) NOT NULL CHECK (device_fingerprint ~ '^[0-9a-f]{64}$'),
  user_code_mac char(64) NOT NULL UNIQUE CHECK (user_code_mac ~ '^[0-9a-f]{64}$'),
  device_code_mac char(64) NOT NULL UNIQUE CHECK (device_code_mac ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  expires_at timestamptz NOT NULL,
  state text NOT NULL DEFAULT 'pending'
    CHECK (state IN ('pending','approved','denied','locked','consumed','expired')),
  attempts smallint NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
  owner_sub text CHECK (owner_sub IS NULL OR length(owner_sub) BETWEEN 1 AND 256),
  CHECK (expires_at > created_at AND expires_at <= created_at + interval '5 minutes'),
  CHECK (
    (state IN ('pending','locked') AND owner_sub IS NULL) OR
    (state IN ('approved','denied','consumed') AND owner_sub IS NOT NULL) OR
    state = 'expired'
  ),
  CHECK (state <> 'locked' OR attempts = 5)
);
CREATE INDEX pairing_challenges_expiry_idx ON pairing_challenges(expires_at);
