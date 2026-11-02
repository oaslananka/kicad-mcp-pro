-- One-time authorization receipt ledger; not an issuer or owner authenticator.
-- No public HTTP route, owner credential, local path, access token, or secret
-- may be persisted here. Only a separately verified owner authority may issue
-- an approved row. Main Cloud does not wire such an authority.
CREATE TABLE owner_read_approvals (
  request_id uuid PRIMARY KEY,
  owner_sub text NOT NULL CHECK(length(owner_sub) BETWEEN 1 AND 256),
  client_id text NOT NULL CHECK(length(client_id) BETWEEN 1 AND 1024),
  device_id uuid NOT NULL,
  project_id uuid NOT NULL,
  cloud_origin text NOT NULL CHECK(length(cloud_origin) BETWEEN 9 AND 256
    AND cloud_origin LIKE 'https://%'),
  operation text NOT NULL CHECK(operation = 'project_summary'),
  issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  CHECK(expires_at > issued_at AND expires_at <= issued_at + interval '30 seconds'),
  CHECK(consumed_at IS NULL OR consumed_at >= issued_at)
);
CREATE INDEX owner_read_approvals_expiry ON owner_read_approvals(expires_at);
