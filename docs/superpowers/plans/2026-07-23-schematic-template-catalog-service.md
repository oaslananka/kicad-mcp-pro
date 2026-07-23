# Schematic Template Catalog Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract bundled subcircuit template discovery and detail rendering from FastMCP registration into a directly testable catalog service.

**Architecture:** Add one FastMCP-free service and one thin adapter. Keep `src/kicad_mcp/tools/schematic.py` as the composition root by injecting the bundled template directory and a lazy PyYAML loader.

**Tech Stack:** Python 3.13, FastMCP, PyYAML, pytest, Ruff, mypy, Pyright, existing architecture and metadata generators.

## Global Constraints

- Preserve both public tool names, signatures, descriptions, schemas, annotations, sorting, truncation, ordering, formatting, lazy PyYAML behavior, errors, and result strings.
- Do not add runtime dependencies or mutation behavior.
- Keep the new adapter `register()` function at or below 300 lines.
- Keep domain code independent of FastMCP and `tools.schematic`.
- Keep full-server metadata and the committed tool-surface snapshot unchanged.

---

### Task 1: Add the FastMCP-free template catalog service

**Files:**
- Create: `src/kicad_mcp/schematic/template_catalog.py`
- Create: `tests/unit/test_schematic_template_catalog_service.py`

**Interfaces:**
- Produces: `SchematicTemplateCatalogService.list_templates() -> str`
- Produces: `SchematicTemplateCatalogService.template_info(template_name: str) -> str`

- [ ] Write direct failing tests for missing and empty directories, filename sorting, name fallback, first-line description truncation, parameter order, per-file parse failures, missing templates, absent PyYAML, parse errors, complete section rendering, and omission of empty sections.
- [ ] Run `uv run --all-extras pytest -q tests/unit/test_schematic_template_catalog_service.py`; expect collection failure because the module is absent.
- [ ] Implement the minimal injected service while preserving the legacy output byte-for-byte.
- [ ] Run service tests, Ruff, mypy, and scoped Pyright; expect all pass.
- [ ] Commit with `refactor(schematic): extract template catalog service`.

### Task 2: Add the thin adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_template_catalog.py`
- Create: `tests/unit/test_schematic_template_catalog_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicTemplateCatalogService`
- Produces: `SchematicTemplateCatalogDependencies(service: SchematicTemplateCatalogService)`
- Produces: `register(mcp: FastMCP, dependencies: SchematicTemplateCatalogDependencies) -> None`

- [ ] Write failing adapter tests for exact names, descriptions, required fields, schemas, headless metadata, and delegation.
- [ ] Run the adapter test; expect collection failure because the adapter is absent.
- [ ] Implement registration and composition wiring; remove the two nested legacy tool functions.
- [ ] Run service/adapter and focused template/schematic integration tests; expect all pass.
- [ ] Commit with `refactor(schematic): delegate template catalog registration`.

### Task 3: Enforce architecture and public-contract stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_template_catalog_architecture.py`

- [ ] Write failing architecture tests for service purity, adapter isolation, and the 300-line limit.
- [ ] Add both modules to the architecture policy and run the checker.
- [ ] Compare exact full-server metadata for the two tools against `main` and run the committed tool-surface snapshot.
- [ ] Commit with `test(architecture): guard template catalog boundaries`.

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-23-schematic-template-catalog-service.md`

- [ ] Run focused service/adapter coverage with the two new modules; require at least 83%.
- [ ] Run metadata, format, Ruff, mypy, scoped Pyright, architecture, workflow security, strict MkDocs, generated docs, snapshot, latency, Bandit, dependency audit, package build, Semgrep, OSV-Scanner, and full unit gates.
- [ ] Record exact surface equality, focused/full test counts, coverage, register spans, and security/package outcomes.
- [ ] Commit with `docs(architecture): record template catalog evidence`.

### Task 5: Open, review, and merge the pull request

- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect all bot/agent comments, reviews, and GraphQL review threads.
- [ ] Address every actionable finding and rerun affected checks.
- [ ] Merge only after all required checks pass and the merge state is clean.
- [ ] Update `main` and remove the worktree and local/remote topic branch.
