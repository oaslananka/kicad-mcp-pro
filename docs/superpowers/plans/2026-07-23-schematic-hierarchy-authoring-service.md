# Schematic Hierarchy Authoring Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract child-sheet and hierarchy-label authoring from FastMCP registration into a directly testable schematic domain service.

**Architecture:** Add one pure orchestration service and one thin FastMCP adapter. Keep `src/kicad_mcp/tools/schematic.py` as the composition root by injecting existing target, grid, transaction, serializer, and reload helpers.

**Tech Stack:** Python 3.13, FastMCP, Pydantic, kicad-sch-api, pytest, Ruff, mypy, Pyright, existing architecture and metadata generators.

## Global Constraints

- Preserve the three public tool names, signatures, descriptions, schemas, annotations, profiles, defaults, aliases, and result strings.
- Preserve lazy dependency loading, child-file behavior, transaction semantics, and reload ordering.
- Do not add runtime dependencies.
- Keep the new adapter `register()` function at or below 300 lines.
- Keep domain code independent of FastMCP and `tools.schematic`.

---

### Task 1: Add the FastMCP-free hierarchy service

**Files:**
- Create: `src/kicad_mcp/schematic/hierarchy_authoring.py`
- Create: `tests/unit/test_schematic_hierarchy_authoring_service.py`

**Interfaces:**
- Produces: `SchematicHierarchyAuthoringService.create_sheet(name, filename, x_mm, y_mm, snap_to_grid) -> str`
- Produces: `SchematicHierarchyAuthoringService.add_hierarchical_label(text, x_mm, y_mm, shape, rotation, snap_to_grid, justify, sheet, sheet_file) -> str`
- Produces: `SchematicHierarchyAuthoringService.add_global_label(text, x_mm, y_mm, shape, rotation, snap_to_grid, justify, sheet, sheet_file) -> str`

- [x] Write direct failing tests for missing dependency, duplicate/existing/new child files, failures, snapping, targeting, label block arguments, transaction target, reload order, and exact results.
- [x] Run `uv run --all-extras pytest -q tests/unit/test_schematic_hierarchy_authoring_service.py`; expect collection failure because the module is absent.
- [x] Implement the minimal injected service while preserving current strings and warning fields.
- [x] Run service tests, Ruff, mypy/Pyright for the new module; expect all pass.
- [x] Commit with `refactor(schematic): extract hierarchy authoring service`.

### Task 2: Add the thin adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_hierarchy_authoring.py`
- Create: `tests/unit/test_schematic_hierarchy_authoring_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicHierarchyAuthoringService`
- Produces: `SchematicHierarchyAuthoringDependencies(service: SchematicHierarchyAuthoringService)`
- Produces: `register(mcp: FastMCP, dependencies: SchematicHierarchyAuthoringDependencies) -> None`

- [x] Write failing adapter tests for exact names, descriptions, defaults, required fields, aliases, validation, metadata, and delegation.
- [x] Run the adapter test; expect collection failure because the adapter is absent.
- [x] Implement registration and composition wiring; remove the three nested legacy tool functions.
- [x] Run service/adapter and focused schematic integration tests; expect all pass.
- [x] Commit with `refactor(schematic): delegate hierarchy authoring registration`.

### Task 3: Enforce architecture and public-contract stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_hierarchy_authoring_architecture.py`

- [x] Write failing architecture tests for service purity, adapter isolation, and the 300-line limit.
- [x] Add both modules to the architecture policy and run the checker.
- [x] Compare exact full-server metadata for the three tools against `main` and run the committed tool-surface snapshot.
- [x] Commit with `test(architecture): guard hierarchy authoring boundaries`.

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-23-schematic-hierarchy-authoring-service.md`

- [x] Run focused service/adapter coverage with the two new modules; require at least 83%.
- [x] Run metadata, format, Ruff, mypy, scoped Pyright, architecture, workflow security, strict MkDocs, generated docs, snapshot, latency, Bandit, dependency audit, package build, and full unit gates.
- [x] Record exact surface equality, focused/full test counts, coverage, register spans, and security/package outcomes.
- [x] Commit with `docs(architecture): record hierarchy authoring evidence`.

## Verification Evidence

- Exact full-server metadata for `sch_create_sheet`, `sch_add_hierarchical_label`, and `sch_add_global_label` matches `main`: names, descriptions, input schemas, defaults, aliases, and annotations are identical.
- The committed tool-surface snapshot passes without regeneration.
- The main schematic `register()` span decreased from 2,403 to 2,259 lines; the hierarchy-authoring adapter `register()` spans 119 lines.
- Focused service, registration, architecture, and schematic integration coverage passed: 156 tests.
- The extracted service and adapter have 100% focused line coverage.
- The full unit suite passed across 1,670 collected tests with five expected skips and one pre-existing async-mock warning.
- Metadata, formatting, Ruff, mypy, scoped strict Pyright, architecture, generated tool documentation, workflow policy/security, strict MkDocs, tool-surface snapshot, latency benchmark, Bandit, dependency audit, and package build gates pass.
- OSV-Scanner 2.4.0 inspected four lockfiles representing 442 dependency entries and reported no known vulnerabilities.
- SonarQube CLI secret analysis completed with no findings. Full Sonar code/dependency analysis could not run because the service account has no saved SonarQube connection; repository SonarQube Cloud Automatic Analysis remains unchanged.
- Semgrep CI reported zero findings, but its Pro cross-file engine hit an internal cache-unmarshal error. A separate scan of all four changed implementation/test files completed with 290 OSS rules, zero findings, and zero scan errors. The pull request Semgrep Cloud check remains mandatory before merge.
- No public tool contract, child-sheet path normalization, lazy dependency loading, grid snapping, transaction target, warning fields, result strings, or reload ordering changed.

### Task 5: Open, review, and merge the pull request

- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect all bot/agent comments, reviews, and GraphQL review threads.
- [ ] Address every actionable finding and rerun affected checks.
- [ ] Merge only after all required checks pass and the merge state is clean.
- [ ] Update `main` and remove the worktree and local/remote topic branch.
