-- Enforce revocation at the resource-server edge even for signed JWTs.
-- A later project re-grant must never reactivate an earlier access token.
CREATE TABLE IF NOT EXISTS client_token_cutoffs (
  owner_sub text NOT NULL,
  client_id text NOT NULL CHECK (length(client_id) BETWEEN 1 AND 1024),
  revoked_at timestamptz NOT NULL,
  PRIMARY KEY(owner_sub,client_id)
);
