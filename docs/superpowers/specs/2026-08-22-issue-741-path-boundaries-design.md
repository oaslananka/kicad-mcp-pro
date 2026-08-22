# Issue #741 PR-A Path-Boundary Hardening Design

## Goal

Eliminate the two highest-confidence user-controlled path traversal surfaces in the MCP tool layer without changing public MCP names, schemas, descriptions, annotations, or normal in-bound behavior:

- `project_embed_file`
- `lib_set_3d_model_path` / `lib_remove_3d_model` / `lib_bulk_assign_3d_models` footprint-library resolution

## Security boundary

`project_embed_file` may read a relative file from the active project. An absolute source path is allowed only when it resolves inside the configured workspace. Traversal, foreign-platform absolute paths, and symlink escapes outside the relevant root must fail closed with the repository's existing `UnsafePathError` semantics.

The `library` and `footprint` arguments in 3D-model tools are identifiers, not arbitrary filesystem paths. They must be portable single path components. Separators, absolute paths, parent traversal, Windows drive/UNC forms, and symlink escapes outside `footprint_library_dir` are rejected. Existing valid library/footprint names, including spaces and Unicode, remain accepted.

`model_path` is content written into a KiCad footprint, not a host filesystem access performed by these tools, so it is deliberately out of scope for PR-A.

## Implementation approach

Reuse the existing path-safety primitives instead of adding a new security abstraction:

- `resolve_under(root, raw_path, allow_absolute=...)`
- `relative_subpath(raw_path)` / existing `UnsafePathError`
- `KiCadMCPConfig.resolve_within_project()`

For embedded files, resolve relative paths through the active project boundary and absolute paths through the configured workspace boundary before any existence/stat/read operation.

For 3D footprint resolution, validate `library` and `footprint` as single portable path components before constructing candidates, then resolve every candidate under `footprint_library_dir`. Bulk-library resolution uses the same component validation and rooted resolution. This keeps the write target rooted even when a library directory is a symlink.

## Compatibility constraints

- No public MCP parameter/schema/description/metadata changes.
- No tool-order changes.
- No new dependency.
- Existing not-found wording for valid names remains unchanged.
- Existing max embedded-file size remains 1,000,000 bytes.
- Existing absolute embedded-file behavior is preserved when the path is inside an explicitly configured workspace.
- `model_path` string serialization behavior remains unchanged.

## Testing

Strict TDD. Before production edits, add failing tests for:

- relative embedded source inside project remains accepted;
- absolute embedded source inside explicit workspace remains accepted;
- absolute source outside workspace is rejected;
- `../` relative traversal is rejected;
- symlink inside workspace/project pointing outside is rejected;
- foreign Windows absolute/UNC source is rejected on non-Windows hosts;
- 3D `library` traversal/absolute/separator forms are rejected;
- 3D `footprint` traversal/absolute/separator forms are rejected;
- 3D library symlink escaping `footprint_library_dir` is rejected;
- valid spaces/Unicode library and footprint names still resolve;
- bulk assignment uses the same safe library boundary.

After GREEN, run focused tests, Ruff, Mypy, architecture/meta/package checks, full unit suite, public descriptor parity, and GitHub CI/security/Sonar. Acceptance requires no new Sonar security issue and removal of the corresponding #741 blocker findings after merge; PR-B/C remain separate.
