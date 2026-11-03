-- Isolated, non-production passkey registration challenges.
-- Registration MUST NOT activate a credential or issue a project-read receipt.
-- An independently authenticated owner operator must explicitly activate a
-- verified, registered passkey using a separate administrative trust boundary.
CREATE TABLE owner_read_passkey_registrations (
  request_id uuid PRIMARY KEY,
  owner_sub text NOT NULL CHECK(length(owner_sub) BETWEEN 1 AND 256),
  challenge_digest bytea NOT NULL UNIQUE CHECK(octet_length(challenge_digest)=32),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  CHECK(expires_at > created_at
    AND expires_at <= created_at + interval '120 seconds'),
  CHECK(used_at IS NULL OR used_at >= created_at)
);
CREATE INDEX owner_read_passkey_registrations_expiry
  ON owner_read_passkey_registrations(expires_at);

CREATE FUNCTION owner_read_registration_used_once()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.used_at IS NOT NULL THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='passkey registration challenge already consumed';
  END IF;
  IF NEW.used_at IS NULL OR NEW.used_at < OLD.created_at THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='invalid registration consumption timestamp';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER owner_read_registration_used_once
BEFORE UPDATE OF used_at ON owner_read_passkey_registrations
FOR EACH ROW EXECUTE FUNCTION owner_read_registration_used_once();
