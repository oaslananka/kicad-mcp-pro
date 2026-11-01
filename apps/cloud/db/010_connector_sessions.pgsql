-- Metadata-only, unexposed server-side connector session record.
-- This does not create a bearer credential or authorize local KiCad actions.
CREATE TABLE connector_sessions (
  id uuid PRIMARY KEY,
  device_id uuid NOT NULL,
  owner_sub text NOT NULL CHECK(length(owner_sub) BETWEEN 1 AND 256),
  handshake_id uuid NOT NULL UNIQUE
    REFERENCES device_handshake_challenges(id) ON DELETE CASCADE,
  connection_digest char(64) NOT NULL UNIQUE
    CHECK(connection_digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  state text NOT NULL DEFAULT 'pending'
    CHECK(state IN ('pending','active','closed','revoked','expired')),
  last_sequence bigint NOT NULL DEFAULT 0 CHECK(last_sequence >= 0),
  FOREIGN KEY(device_id,owner_sub) REFERENCES devices(id,owner_sub) ON DELETE CASCADE,
  CHECK(expires_at > created_at AND expires_at <= created_at + interval '5 minutes')
);
CREATE UNIQUE INDEX connector_session_one_live_device
  ON connector_sessions(device_id) WHERE state IN ('pending','active');
CREATE INDEX connector_sessions_owner ON connector_sessions(owner_sub,device_id);
CREATE INDEX connector_sessions_expiry ON connector_sessions(expires_at);
