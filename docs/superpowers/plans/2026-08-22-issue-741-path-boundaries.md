# Issue #741 PR-A Path-Boundary Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the user-controlled filesystem traversal paths in embedded-file reads and 3D footprint-library writes while preserving the exact public MCP contract and valid in-bound behavior.

**Architecture:** Reuse the repository's existing rooted path-safety primitives. Embedded-file reads resolve relative paths inside the active project and absolute paths inside the configured workspace; 3D library/footprint selectors are validated as portable single path components and every candidate path is resolved under `footprint_library_dir` before file access.

**Tech Stack:** Python 3.13, FastMCP, pytest/anyio, existing `kicad_mcp.path_safety`, Ruff, Mypy, repository meta/package/security checks.

**Spec:** `docs/superpowers/specs/2026-08-22-issue-741-path-boundaries-design.md`

## Global Constraints

- Base is exact `main@a0e06f53510dc90a5ba32abcc51e1a4d01403d42`.
- Public MCP names, parameter schemas/defaults, descriptions, annotations, tool order, and normal success text must remain unchanged.
- No new dependency and no Sonar/CodeQL/Trivy suppression or gate weakening.
- `project_embed_file` may read relative files from the active project; absolute files are allowed only inside the configured workspace.
- 3D `library` and `footprint` values are identifiers and must be portable single path components; spaces and Unicode remain valid.
- 3D `model_path` is serialized content and is not a host filesystem read/write path in this tranche.
- Symlink escapes must fail closed after resolution.
- Strict TDD: no production edit before the corresponding RED test is observed.

---

### Task 1: Embedded-file source boundary

**Files:**
- Modify first: `tests/unit/test_project_embedded_files.py`
- Modify only after RED: `src/kicad_mcp/tools/embedded_files.py`

**Interfaces:**
- Consumes: `get_config()`, `KiCadMCPConfig.resolve_within_project()`, `resolve_under()`.
- Produces: unchanged public `project_embed_file(source_path, target_name=None, description="")` contract with safe source resolution.

- [ ] **Step 1: Add failing security behavior tests**

Add a small project fixture helper in the test module and independent tests that exercise the real FastMCP tool. Required cases:

```python
# relative in-project source succeeds
source = project / "docs" / "note.txt"
result = await call_tool_text(server, "project_embed_file", {"source_path": "docs/note.txt"})
assert "Embedded" in result

# absolute source outside configured workspace fails
outside = tmp_path / "outside.txt"
result = await call_tool_text(server, "project_embed_file", {"source_path": str(outside)})
assert "escapes workspace root" in result
```

Also cover `../outside.txt`, a symlink under the project/workspace that resolves outside, and on non-Windows hosts a Windows drive/UNC source. Add a positive test with explicit `KICAD_MCP_WORKSPACE_ROOT` (or direct config fixture if repository conventions require) proving an absolute file inside a workspace but outside the project remains accepted.

- [ ] **Step 2: Run embedded tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_project_embedded_files.py
```

Expected: new outside-workspace/traversal tests fail because current absolute paths bypass the configured resolver. If a test errors for fixture/setup reasons, fix the test and rerun until the failure is caused by the unsafe behavior.

- [ ] **Step 3: Implement minimal safe source resolution**

In `src/kicad_mcp/tools/embedded_files.py`, import the existing rooted resolver and replace the direct absolute-path bypass with a private resolver equivalent to:

```python
def _resolve_embed_source(source_path: str) -> Path:
    cfg = get_config()
    raw = Path(source_path)
    if raw.is_absolute():
        return resolve_under(cfg.workspace, source_path)
    return cfg.resolve_within_project(source_path)
```

Call this before `exists()`, `is_file()`, `stat()`, or `read_bytes()`. Do not catch `UnsafePathError`; preserve the repository's fail-closed error surface.

- [ ] **Step 4: Verify GREEN and static quality**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_project_embedded_files.py tests/unit/test_path_safety.py
.venv/bin/python -m ruff check src/kicad_mcp/tools/embedded_files.py tests/unit/test_project_embedded_files.py
.venv/bin/python -m ruff format --check src/kicad_mcp/tools/embedded_files.py tests/unit/test_project_embedded_files.py
.venv/bin/python -m mypy src/kicad_mcp/tools/embedded_files.py tests/unit/test_project_embedded_files.py
```

Expected: all exit 0.

---

### Task 2: 3D footprint-library selector boundary

**Files:**
- Modify first: `tests/unit/test_library_3d_models.py`
- Modify only after RED: `src/kicad_mcp/tools/three_d_models.py`

**Interfaces:**
- Consumes: existing `relative_subpath()` / `resolve_under()` / `UnsafePathError` path policy.
- Produces: safe `_find_footprint_file(library, footprint)` and safe bulk library directory resolution with unchanged valid-name behavior.

- [ ] **Step 1: Add failing selector and symlink tests**

Add direct helper tests and real-tool tests where practical. Required assertions:

```python
with pytest.raises(UnsafePathError):
    _find_footprint_file("../outside", "Part")

with pytest.raises(UnsafePathError):
    _find_footprint_file("Library", "../Part")
```

Also reject `/absolute`, `C:\\absolute`, UNC, embedded `/` or `\\` separators, and a `footprint_library_dir` child symlink that resolves outside. Add a positive case proving names such as `My Library µ` and `Footprint Ω` resolve when corresponding files exist. Add a bulk-assignment FastMCP test proving unsafe `library` cannot redirect writes outside the configured footprint library root.

- [ ] **Step 2: Run 3D tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_library_3d_models.py
```

Expected: traversal/separator/symlink cases fail against the current direct path concatenation. Fix only test setup errors until the unsafe behavior is the observed reason.

- [ ] **Step 3: Implement minimal selector validation and rooted candidate resolution**

Add one private helper that validates a selector as exactly one portable path component. It must:

```python
candidate = relative_subpath(value)
if not value or value in {".", ".."} or "/" in value or "\\" in value or len(candidate.parts) != 1:
    raise UnsafePathError(f"{label} must be a single path component inside the footprint library.")
return candidate.name
```

Use the validated values before constructing candidates. Resolve candidates with `resolve_under(lib_dir, candidate, allow_absolute=False)` so symlink escapes are detected. Use the same validated/rooted library-directory resolution in `lib_bulk_assign_3d_models`; do not duplicate an unsafe path-building branch.

Do not validate or rewrite `model_path` beyond existing behavior because it is serialized into the footprint rather than dereferenced by this tool.

- [ ] **Step 4: Verify GREEN and static quality**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_library_3d_models.py tests/unit/test_path_safety.py
.venv/bin/python -m ruff check src/kicad_mcp/tools/three_d_models.py tests/unit/test_library_3d_models.py
.venv/bin/python -m ruff format --check src/kicad_mcp/tools/three_d_models.py tests/unit/test_library_3d_models.py
.venv/bin/python -m mypy src/kicad_mcp/tools/three_d_models.py tests/unit/test_library_3d_models.py
```

Expected: all exit 0.

---

### Task 3: Contract parity and security regression guard

**Files:**
- Create first: `tests/unit/test_issue_741_path_boundaries.py`
- Modify production only if RED exposes a missing guarantee.

**Interfaces:**
- Consumes: public server tool descriptors and the two hardened modules.
- Produces: regression coverage that prevents direct unsafe absolute embedded reads and 3D selector path construction from returning.

- [ ] **Step 1: Capture base public contracts under `/tmp`**

Use exact base commit `a0e06f53510dc90a5ba32abcc51e1a4d01403d42` to capture descriptors for:

- `project_embed_file`
- `lib_set_3d_model_path`
- `lib_remove_3d_model`
- `lib_bulk_assign_3d_models`

Record name, index/order, parameter schema/defaults, description, annotations, and output schema where present. Do not commit generated captures.

- [ ] **Step 2: Add regression/architecture tests**

Use AST/source inspection to assert `project_embed_file` resolves its source before filesystem read operations and that 3D lookup/bulk code routes user selectors through the safe helper/rooted resolver. Compare current public descriptors to the base capture exactly.

- [ ] **Step 3: Run regression tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_issue_741_path_boundaries.py tests/unit/test_project_embedded_files.py tests/unit/test_library_3d_models.py tests/unit/test_path_safety.py
```

Expected: all exit 0 after Tasks 1-2 are GREEN.

---

### Task 4: Repository-wide verification and PR publication

**Files:**
- Review all changed files; no unrelated modifications.

**Interfaces:**
- Produces: a reviewable PR-A linked to #741 with fresh local and GitHub evidence.

- [ ] **Step 1: Run local verification**

Run repository-native commands, using the pinned environment created by `scripts/bootstrap-dev.sh --core-only`:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy src tests
pnpm run check:meta
pnpm run package:check
.venv/bin/python scripts/run_pytest.py unit
```

Also run `git diff --check` and inspect the complete diff for debug/temp/generated/secret/unrelated changes.

- [ ] **Step 2: Verify public descriptor parity**

Compare the full `agent_full` public descriptor set and order against exact base. Expected: identical count/order/descriptors; only internal rejection behavior for unsafe paths changes.

- [ ] **Step 3: Commit and publish through the repository-safe GitHub path**

Commit with a focused security message, publish the verified tree without using unavailable local credentials, open one PR linked to #741, and add pre-PR evidence to the issue.

- [ ] **Step 4: Gate merge on current-head CI**

Do not merge until Required PR Gate, coverage, Ubuntu/macOS/Windows server/npm lanes, CodeQL, dependency/security scans, Live Model policy, Sonar Quality Gate, and all required checks are complete and successful. Resolve real review/bot findings in code; do not suppress them.

- [ ] **Step 5: Post-merge exact-main verification**

After squash merge, verify exact merge SHA workflows including full coverage, CodeQL, security/Gitleaks/Scorecard/Live Model/Sonar. Confirm the relevant Sonar blocker findings are removed or reduced as expected, then update #741 before beginning PR-B.
