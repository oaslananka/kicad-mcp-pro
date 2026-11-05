-- Offline-only durable one-use write proof replay fence.
-- This is NOT an edit grant, signed token or executable Connector route.
-- No private keys, local paths, board data or command payloads are stored.
-- Request identifiers are globally unique, including across sessions.
CREATE TABLE connector_write_proof_reservations (
  request_id uuid PRIMARY KEY,
  session_id uuid NOT NULL,
  reserved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  expires_at timestamptz NOT NULL,
  CHECK(expires_at > reserved_at),
  CHECK(expires_at <= reserved_at + interval '10 seconds')
);
CREATE INDEX connector_write_proof_reservations_expiry
  ON connector_write_proof_reservations(expires_at);
