-- Per-source and per-public-key, multi-worker bounded issuance/redemption.
-- Only keyed HMAC digests are stored, never IPs, public keys, codes or tokens.
CREATE TABLE pairing_device_budget (
  budget_key char(64) PRIMARY KEY CHECK(budget_key ~ '^[0-9a-f]{64}$'),
  window_started_at timestamptz NOT NULL,
  attempts smallint NOT NULL CHECK(attempts BETWEEN 1 AND 41)
);
CREATE INDEX pairing_device_budget_expiry ON pairing_device_budget(window_started_at);
