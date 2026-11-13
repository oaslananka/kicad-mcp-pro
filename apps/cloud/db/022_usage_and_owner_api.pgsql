-- Real tool-call telemetry and command-line owner access.
-- No quota, allowance or plan-limit column exists by design: counts are
-- only ever recorded observations, never entitlements.

CREATE TABLE IF NOT EXISTS usage_tool_calls (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  owner_sub text NOT NULL CHECK (length(owner_sub) <= 256),
  client_id text NOT NULL CHECK (length(client_id) <= 1024),
  tool text NOT NULL CHECK (length(tool) <= 128),
  status text NOT NULL CHECK (status IN ('success','error','denied')),
  occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS usage_tool_calls_owner_time
  ON usage_tool_calls(owner_sub, occurred_at DESC);
CREATE INDEX IF NOT EXISTS usage_tool_calls_owner_client
  ON usage_tool_calls(owner_sub, client_id, occurred_at DESC);

-- One-time browser-approved command-line pairing requests. The CLI holds
-- only a random request id; an owner browser session must approve it.
CREATE TABLE IF NOT EXISTS owner_api_cli_requests (
  request_id text PRIMARY KEY CHECK (length(request_id) = 43),
  label text NOT NULL CHECK (length(label) <= 64),
  owner_sub text CHECK (owner_sub IS NULL OR length(owner_sub) <= 256),
  token_hash text CHECK (token_hash IS NULL OR length(token_hash) = 64),
  state text NOT NULL CHECK (state IN ('pending','approved','claimed','expired')),
  poll_count integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT owner_api_cli_requests_approved_state
    CHECK (state = 'pending' OR (owner_sub IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS owner_api_cli_requests_created
  ON owner_api_cli_requests(created_at);

-- Issued command-line management tokens. Only the SHA-256 hash is stored;
-- the plaintext token is shown once at approval time and never again.
CREATE TABLE IF NOT EXISTS owner_api_tokens (
  token_hash text PRIMARY KEY CHECK (length(token_hash) = 64),
  owner_sub text NOT NULL CHECK (length(owner_sub) <= 256),
  label text NOT NULL CHECK (length(label) <= 64),
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz
);

CREATE INDEX IF NOT EXISTS owner_api_tokens_owner
  ON owner_api_tokens(owner_sub);
