-- Append-only issuer challenge replay protection. Even an issuer principal
-- granted UPDATE(used_at) must not reset/rearm a previously attempted
-- passkey assertion. A correctly signed WebAuthn response alone is not an
-- authorization if a challenge has been used or has expired.
CREATE FUNCTION owner_read_webauthn_challenge_used_once()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.used_at IS NOT NULL THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='owner webauthn challenge already consumed';
  END IF;
  IF NEW.used_at IS NULL OR NEW.used_at < OLD.issued_at
      OR NEW.used_at >= OLD.expires_at THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='invalid owner webauthn challenge consumption timestamp';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER owner_read_webauthn_challenge_used_once
BEFORE UPDATE OF used_at ON owner_read_webauthn_challenges
FOR EACH ROW EXECUTE FUNCTION owner_read_webauthn_challenge_used_once();
