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

- [ ] Write direct failing tests for missing dependency, duplicate/existing/new child files, failures, snapping, targeting, label block arguments, transaction target, reload order, and exact results.
- [ ] Run `uv run --all-extras pytest -q tests/unit/test_schematic_hierarchy_authoring_service.py`; expect collection failure because the module is absent.
- [ ] Implement the minimal injected service while preserving current strings and warning fields.
- [ ] Run service tests, Ruff, mypy/Pyright for the new module; expect all pass.
- [ ] Commit with `refactor(schematic): extract hierarchy authoring service`.

### Task 2: Add the thin adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_hierarchy_authoring.py`
- Create: `tests/unit/test_schematic_hierarchy_authoring_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicHierarchyAuthoringService`
- Produces: `SchematicHierarchyAuthoringDependencies(service: SchematicHierarchyAuthoringService)`
- Produces: `register(mcp: FastMCP, dependencies: SchematicHierarchyAuthoringDependencies) -> None`

- [ ] Write failing adapter tests for exact names, descriptions, defaults, required fields, aliases, validation, metadata, and delegation.
- [ ] Run the adapter test; expect collection failure because the adapter is absent.
- [ ] Implement registration and composition wiring; remove the three nested legacy tool functions.
- [ ] Run service/adapter and focused schematic integration tests; expect all pass.
- [ ] Commit with `refactor(schematic): delegate hierarchy authoring registration`.

### Task 3: Enforce architecture and public-contract stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_hierarchy_authoring_architecture.py`

- [ ] Write failing architecture tests for service purity, adapter isolation, and the 300-line limit.
- [ ] Add both modules to the architecture policy and run the checker.
- [ ] Compare exact full-server metadata for the three tools against `main` and run the committed tool-surface snapshot.
- [ ] Commit with `test(architecture): guard hierarchy authoring boundaries`.

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-23-schematic-hierarchy-authoring-service.md`

- [ ] Run focused service/adapter coverage with the two new modules; require at least 83%.
- [ ] Run metadata, format, Ruff, mypy, scoped Pyright, architecture, workflow security, strict MkDocs, generated docs, snapshot, latency, Bandit, dependency audit, package build, and full unit gates.
- [ ] Record exact surface equality, focused/full test counts, coverage, register spans, and security/package outcomes.
- [ ] Commit with `docs(architecture): record hierarchy authoring evidence`.

### Task 5: Open, review, and merge the pull request

- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect all bot/agent comments, reviews, and GraphQL review threads.
- [ ] Address every actionable finding and rerun affected checks.
- [ ] Merge only after all required checks pass and the merge state is clean.
- [ ] Update `main` and remove the worktree and local/remote topic branch.
