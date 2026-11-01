-- Append-only migration: prevent a consumption-only database role from
-- clearing consumed_at and replaying a previously approved owner read.
-- In particular, UPDATE(consumed_at) privilege alone is NOT a replay fence.
-- The issuer and consumer remain distinct; this does not create an issuer.
CREATE FUNCTION owner_read_approval_consumed_once()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD.consumed_at IS NOT NULL THEN
    RAISE EXCEPTION USING ERRCODE = '23514',
      MESSAGE = 'owner approval already consumed';
  END IF;
  IF NEW.consumed_at IS NULL OR
     NEW.consumed_at < OLD.issued_at OR
     NEW.consumed_at >= OLD.expires_at THEN
    RAISE EXCEPTION USING ERRCODE = '23514',
      MESSAGE = 'owner approval consumption timestamp invalid';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER owner_read_approval_consumed_once
BEFORE UPDATE OF consumed_at ON owner_read_approvals
FOR EACH ROW
EXECUTE FUNCTION owner_read_approval_consumed_once();
