-- Owner-controlled read-only Connector switch. Missing row means OFF.
-- No project files, paths, tokens or private device keys are stored.
CREATE TABLE IF NOT EXISTS connector_managed_read_access (
  project_id uuid PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  enabled boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now()
);
