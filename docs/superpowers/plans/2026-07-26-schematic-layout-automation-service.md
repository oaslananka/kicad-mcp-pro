# Schematic Layout Automation Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract four schematic layout/readability tools into a FastMCP-independent service and thin adapter without changing the public MCP contract.

**Architecture:** `SchematicLayoutAutomationService` owns existing workflows through injected collaborators. `schematic_layout_automation.register()` preserves public signatures and decorators. `tools.schematic.register()` only composes dependencies and delegates registration.

**Tech Stack:** Python 3.13, FastMCP, pytest, Ruff, mypy, repository architecture and metadata checks.

## Global Constraints

- Preserve public tool names, schemas, descriptions, annotations, metadata, response text, transaction behavior, and reload behavior.
- Keep the service independent of FastMCP and `kicad_mcp.tools.schematic`.
- Keep the adapter free of domain/file mutation logic.
- Use the project-pinned uv 0.10.8 executable.
- Make no unrelated refactors or feature changes.

---

### Task 1: Lock the architecture and adapter contract with failing tests

**Files:**
- Create: `tests/unit/test_schematic_layout_automation_architecture.py`
- Create: `tests/unit/test_schematic_layout_automation_registration.py`

**Interfaces:**
- Consumes: current four tool signatures and metadata from `tools.schematic`.
- Produces: required module names `schematic.layout_automation` and `tools.schematic_layout_automation`, plus `register(mcp, dependencies)`.

- [ ] Add an AST architecture test that requires a service module with no FastMCP/registry import and requires delegation from `tools.schematic`.
- [ ] Add a registration test that imports the new adapter, records registered functions, and asserts exact names, signatures, headless metadata, and service delegation.
- [ ] Run the two tests and verify collection/import fails because the new modules do not exist.
- [ ] Commit the red tests.

### Task 2: Implement the FastMCP-independent service test-first

**Files:**
- Create: `tests/unit/test_schematic_layout_automation_service.py`
- Create: `src/kicad_mcp/schematic/layout_automation.py`

**Interfaces:**
- Produces: `SchematicLayoutAutomationService.auto_place_symbols()`, `.autoplace_fields()`, `.fix_readability()`, and `.auto_place_functional()` returning `str`.
- Consumes: injected active-file, parser, loader, placement, transaction, QA, design-intent, geometry, warning, and constant collaborators.

- [ ] Write service tests for empty schematics, load/save failure, obstacle-aware placement, dry-run field placement, transactional field placement, readability stop/apply paths, anchors, missing references, zones, and overflow reporting.
- [ ] Run focused service tests and verify they fail because the service is absent.
- [ ] Implement typed protocols and the smallest service implementation copied behavior-for-behavior from the composition root.
- [ ] Run service tests until green.
- [ ] Run Ruff and mypy on the new service and test file.
- [ ] Commit the service and tests.

### Task 3: Add the thin adapter and delegate from the composition root

**Files:**
- Create: `src/kicad_mcp/tools/schematic_layout_automation.py`
- Modify: `src/kicad_mcp/tools/schematic.py`
- Modify: `scripts/check_architecture_boundaries.py`

**Interfaces:**
- Produces: `SchematicLayoutAutomationDependencies(service=...)` and `register(mcp, dependencies)`.
- Consumes: `SchematicLayoutAutomationService` from Task 2.

- [ ] Implement the adapter with exact signatures, decorators, and docstrings, delegating one-to-one to the service.
- [ ] Compose the service in `tools.schematic.register()` using existing helpers/constants.
- [ ] Remove only the four original nested tool implementations.
- [ ] Extend architecture policy for the service and adapter boundary.
- [ ] Run registration and architecture tests until green.
- [ ] Commit adapter/delegation changes.

### Task 4: Prove contract preservation and repository health

**Files:**
- Modify only generated files if repository checks require intentional regeneration; otherwise no files.

**Interfaces:**
- Consumes: completed service and adapter.
- Produces: verification evidence suitable for the PR and issue #434.

- [ ] Run existing focused integration tests for the four tools.
- [ ] Run tool-surface, generated metadata/documentation, architecture, and adapter contract checks.
- [ ] Run full unit tests, Ruff format/check, mypy, and focused coverage.
- [ ] Run `git diff --check` and inspect the final diff for unrelated changes.
- [ ] Push the branch and open a PR referencing #434 without closing it.
