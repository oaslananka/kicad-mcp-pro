# Schematic Layout Inspection Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract schematic bounding-box and free-placement inspection from FastMCP registration into a directly testable domain service.

**Architecture:** Add one pure orchestration service and one thin FastMCP adapter. Keep `src/kicad_mcp/tools/schematic.py` as the composition root by injecting the existing parser, diagnostics, geometry, occupancy, keepout, and free-cell helpers.

**Tech Stack:** Python 3.13, FastMCP, pytest, Ruff, mypy, Pyright, existing architecture and metadata generators.

## Global Constraints

- Preserve both public tool names, signatures, descriptions, schemas, annotations, defaults, count clamping, ordering, formatting, diagnostics, and result strings.
- Do not add runtime dependencies or file mutations.
- Keep the new adapter `register()` function at or below 300 lines.
- Keep domain code independent of FastMCP and `tools.schematic`.
- Keep full-server metadata and the committed tool-surface snapshot unchanged.

---

### Task 1: Add the FastMCP-free layout inspection service

**Files:**
- Create: `src/kicad_mcp/schematic/layout_inspection.py`
- Create: `tests/unit/test_schematic_layout_inspection_service.py`

**Interfaces:**
- Produces: `SchematicLayoutInspectionService.bounding_boxes() -> str`
- Produces: `SchematicLayoutInspectionService.free_placement(count, cell_width_mm, cell_height_mm, keepout_regions) -> str`

- [x] Write direct failing tests for empty diagnostics, exact table formatting, symbol ordering, count clamping, occupancy forwarding, keepout expansion, coordinate rounding, and exact result strings.
- [x] Run `uv run --all-extras pytest -q tests/unit/test_schematic_layout_inspection_service.py`; expect collection failure because the module is absent.
- [x] Implement the minimal injected service while preserving the legacy output byte-for-byte.
- [x] Run the service tests, Ruff, mypy, and scoped Pyright; expect all pass.
- [x] Commit with `refactor(schematic): extract layout inspection service`.

### Task 2: Add the thin adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_layout_inspection.py`
- Create: `tests/unit/test_schematic_layout_inspection_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicLayoutInspectionService`
- Produces: `SchematicLayoutInspectionDependencies(service: SchematicLayoutInspectionService)`
- Produces: `register(mcp: FastMCP, dependencies: SchematicLayoutInspectionDependencies) -> None`

- [x] Write failing adapter tests for exact names, descriptions, defaults, schemas, headless metadata, validation, and argument delegation.
- [x] Run the adapter test; expect collection failure because the adapter is absent.
- [x] Implement registration and composition wiring; remove the two nested legacy tool functions.
- [x] Run service/adapter and focused schematic integration tests; expect all pass.
- [x] Commit with `refactor(schematic): delegate layout inspection registration`.

### Task 3: Enforce architecture and public-contract stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_layout_inspection_architecture.py`

- [x] Write failing architecture tests for service purity, adapter isolation, and the 300-line limit.
- [x] Add both modules to the architecture policy and run the checker.
- [x] Compare exact full-server metadata for the two tools against `main` and run the committed tool-surface snapshot.
- [x] Commit with `test(architecture): guard layout inspection boundaries`.

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-23-schematic-layout-inspection-service.md`

- [x] Run focused service/adapter coverage with the two new modules; require at least 83%.
- [x] Run metadata, format, Ruff, mypy, scoped Pyright, architecture, workflow security, strict MkDocs, generated docs, snapshot, latency, Bandit, dependency audit, package build, and full unit gates.
- [x] Record exact surface equality, focused/full test counts, coverage, register spans, and security/package outcomes.
- [x] Commit with `docs(architecture): record layout inspection evidence`.

## Verification Evidence

- Exact full-server metadata for `sch_get_bounding_boxes` and `sch_find_free_placement` matches `main`: names, descriptions, input schemas, defaults, tuple constraints, and annotations are identical.
- The committed tool-surface snapshot passes without regeneration.
- The main schematic `register()` span decreased from 2,259 to 2,157 lines; the layout-inspection adapter `register()` spans 52 lines.
- Focused service, registration, architecture, schematic integration, extended schematic, and empty-project read coverage passed: 173 tests.
- The extracted service and adapter have 100% focused line coverage.
- The full unit suite passed across 1,681 selected tests with five expected skips and one pre-existing async-mock warning.
- Metadata, formatting, Ruff, mypy, scoped strict Pyright, architecture, generated tool documentation, workflow policy/security, strict MkDocs, tool-surface snapshot, latency benchmark, Bandit, dependency audit, and package build gates pass.
- OSV-Scanner 2.4.0 inspected four lockfiles representing 442 dependency entries and reported no known vulnerabilities.
- Semgrep scanned the five changed implementation, test, and architecture files with 1,198 rules and reported zero findings.
- No public tool contract, parser selection, diagnostics, symbol ordering, bounding-box formatting, occupancy behavior, keepout expansion, count clamping, coordinate rounding, or result string changed.

### Task 5: Open, review, and merge the pull request

- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect all bot/agent comments, reviews, and GraphQL review threads.
- [ ] Address every actionable finding and rerun affected checks.
- [ ] Merge only after all required checks pass and the merge state is clean.
- [ ] Update `main` and remove the worktree and local/remote topic branch.
