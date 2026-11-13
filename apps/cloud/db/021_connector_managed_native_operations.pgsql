-- Explicit operation grants for managed native KiCad metadata reads.
-- Existing owner project-summary grants do NOT imply any native permission.
-- The full managed read switch remains an additional prerequisite.
ALTER TABLE connector_managed_read_access
  ADD COLUMN native_operations text[] NOT NULL DEFAULT '{}'::text[];
ALTER TABLE connector_managed_read_access
  ADD CONSTRAINT managed_native_read_operations_allowlist
  CHECK (native_operations <@ ARRAY[
    'run_drc','project_worker_inspection','project_board_counts','project_schematic_counts'
  ]::text[]);
