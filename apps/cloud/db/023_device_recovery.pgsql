-- A replacement is a one-time transition for the previous owner/device ID.
-- Keep the transition even when either device is removed. It contains only
-- inventory identifiers, never keys, paths, pairing codes or grant data.
CREATE TABLE device_replacements (
  owner_sub text NOT NULL CHECK (length(owner_sub) BETWEEN 1 AND 256),
  previous_device_id uuid NOT NULL,
  replacement_device_id uuid NOT NULL UNIQUE,
  pairing_challenge_id uuid NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (owner_sub, previous_device_id),
  CHECK (previous_device_id <> replacement_device_id)
);
