-- Per-AI-client grant: deny access unless the owner explicitly enables it.
-- Cloud holds opaque IDs, aliases and policies only, never local KiCad data.
CREATE UNIQUE INDEX IF NOT EXISTS projects_owner_id ON projects(owner_sub, id);
CREATE TABLE IF NOT EXISTS project_client_grants (
  project_id uuid NOT NULL,
  owner_sub text NOT NULL,
  client_id text NOT NULL CHECK (length(client_id) BETWEEN 1 AND 1024),
  enabled boolean NOT NULL DEFAULT false,
  max_mode text NOT NULL DEFAULT 'readonly'
    CHECK (max_mode IN ('readonly', 'write', 'manufacturing')),
  PRIMARY KEY(project_id, client_id),
  FOREIGN KEY(owner_sub, project_id) REFERENCES projects(owner_sub, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS project_grants_owner_client
  ON project_client_grants(owner_sub, client_id);
CREATE TABLE IF NOT EXISTS client_grant_audit (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  owner_sub text NOT NULL,
  actor_client_id text NOT NULL,
  project_id uuid NOT NULL,
  operation text NOT NULL CHECK (operation IN ('grant.set')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS client_grant_audit_owner
  ON client_grant_audit(owner_sub, created_at DESC);
