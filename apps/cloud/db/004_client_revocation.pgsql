-- Expand existing metadata-only audit vocabulary for explicit client revocation.
ALTER TABLE client_grant_audit
  DROP CONSTRAINT IF EXISTS client_grant_audit_operation_check;
ALTER TABLE client_grant_audit
  ADD CONSTRAINT client_grant_audit_operation_check
    CHECK (operation IN ('grant.set', 'client.revoke'));
