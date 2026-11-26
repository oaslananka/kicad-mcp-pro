-- Only opt-in resumable initial enrollment writes a receipt.
-- No credentials, pairing secrets, grants or project data are stored here.
-- Existing challenge retention bounds the lifetime after device deletion.
CREATE TABLE device_initial_enrollments (
  pairing_challenge_id uuid PRIMARY KEY REFERENCES pairing_challenges(id) ON DELETE CASCADE,
  device_id uuid NOT NULL UNIQUE,
  owner_sub text NOT NULL CHECK (length(owner_sub) BETWEEN 1 AND 256)
);
