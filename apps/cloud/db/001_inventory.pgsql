-- Control-plane inventory only. NEVER store project paths, KiCad files, tool payloads or tokens.
-- Provision/migrate this database through a controlled admin deployment step.
CREATE TABLE IF NOT EXISTS devices (
  id uuid PRIMARY KEY,
  owner_sub text NOT NULL,
  alias text NOT NULL CHECK (length(alias) BETWEEN 1 AND 120),
  enabled boolean NOT NULL DEFAULT false,
  last_seen_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id, owner_sub)
);
CREATE INDEX IF NOT EXISTS devices_owner ON devices(owner_sub);

CREATE TABLE IF NOT EXISTS projects (
  id uuid PRIMARY KEY,
  owner_sub text NOT NULL,
  device_id uuid NOT NULL,
  alias text NOT NULL CHECK (length(alias) BETWEEN 1 AND 120),
  enabled boolean NOT NULL DEFAULT false,
  max_mode text NOT NULL DEFAULT 'readonly'
    CHECK (max_mode IN ('readonly', 'write', 'manufacturing')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(device_id, id),
  FOREIGN KEY(device_id, owner_sub) REFERENCES devices(id, owner_sub) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS projects_owner ON projects(owner_sub);
-- Composite FK ensures a project can never reference another owner's device.
-- No write/enrollment API is exposed in this initial, read-only Cloud slice.
