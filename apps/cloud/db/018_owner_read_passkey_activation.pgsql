-- Owner passkey activation requires a NEW independent UV assertion.
-- This draft-only DB surface is deliberately separate from registration
-- and project-summary approval, and is NOT wired in production.
CREATE TABLE owner_read_passkey_activations (
  request_id uuid PRIMARY KEY,
  owner_sub text NOT NULL CHECK(length(owner_sub) BETWEEN 1 AND 256),
  credential_id text NOT NULL REFERENCES owner_read_passkeys(credential_id),
  challenge_digest bytea NOT NULL UNIQUE CHECK(octet_length(challenge_digest) = 32),
  created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  CHECK(expires_at > created_at AND expires_at <= created_at + interval '120 seconds'),
  CHECK(used_at IS NULL OR used_at >= created_at)
);
CREATE INDEX owner_read_passkey_activations_expiry
  ON owner_read_passkey_activations(expires_at);

CREATE FUNCTION owner_read_passkey_activation_used_once()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.used_at IS NOT NULL THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='owner passkey activation challenge already used';
  END IF;
  IF NEW.used_at IS NULL OR NEW.used_at < OLD.created_at
     OR NEW.used_at >= OLD.expires_at THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='invalid owner passkey activation timestamp';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER owner_read_passkey_activation_used_once
BEFORE UPDATE OF used_at ON owner_read_passkey_activations
FOR EACH ROW EXECUTE FUNCTION owner_read_passkey_activation_used_once();
