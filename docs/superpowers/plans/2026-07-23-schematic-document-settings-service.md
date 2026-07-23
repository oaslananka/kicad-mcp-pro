# Schematic Document Settings Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract schematic title-block and sheet-size behavior from FastMCP registration into a directly testable document-settings domain service.

**Architecture:** Add one FastMCP-free orchestration service and one thin adapter. Keep `src/kicad_mcp/tools/schematic.py` as the composition root by injecting the current target, parser, transformation, transaction, reload, paper-size, and geometry dependencies.

**Tech Stack:** Python 3.13, FastMCP, pytest, Ruff, mypy, Pyright, existing transaction models and architecture/metadata generators.

## Global Constraints

- Preserve the three public tool names, signatures, descriptions, schemas, annotations, defaults, field ordering, transaction metadata, hashes, reload ordering, error text, and result strings.
- Do not add runtime dependencies or change transaction/approval semantics.
- Keep the new adapter `register()` function at or below 300 lines.
- Keep domain code independent of FastMCP and `tools.schematic`.
- Keep full-server metadata and the committed tool-surface snapshot unchanged.

---

### Task 1: Add the FastMCP-free document settings service

**Files:**
- Create: `src/kicad_mcp/schematic/document_settings.py`
- Create: `tests/unit/test_schematic_document_settings_service.py`

**Interfaces:**
- Produces: `SchematicDocumentSettingsService.set_title_block_info(...) -> str`
- Produces: `SchematicDocumentSettingsService.set_sheet_size(paper: str) -> str`
- Produces: `SchematicDocumentSettingsService.auto_resize_sheet() -> str`

- [ ] Write direct failing tests for empty updates, update ordering, target forwarding, dry-run hashes and verification, committed write/reload order, exact transaction text, invalid paper, already-set paper, missing paper declarations, write failures, usable-grid forwarding, empty symbols, fitting sheets, oversized sheets, and automatic delegation.
- [ ] Run `uv run --all-extras pytest -q tests/unit/test_schematic_document_settings_service.py`; expect collection failure because the module is absent.
- [ ] Implement the minimal injected service while preserving the legacy behavior byte-for-byte.
- [ ] Run service tests, Ruff, mypy, and scoped Pyright; expect all pass.
- [ ] Commit with `refactor(schematic): extract document settings service`.

### Task 2: Add the thin adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_document_settings.py`
- Create: `tests/unit/test_schematic_document_settings_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicDocumentSettingsService`
- Produces: `SchematicDocumentSettingsDependencies(service: SchematicDocumentSettingsService)`
- Produces: `register(mcp: FastMCP, dependencies: SchematicDocumentSettingsDependencies) -> None`

- [ ] Write failing adapter tests for exact names, descriptions, defaults, required/optional fields, schemas, headless metadata, and argument delegation.
- [ ] Run the adapter test; expect collection failure because the adapter is absent.
- [ ] Implement registration and composition wiring; remove the three nested legacy tool functions.
- [ ] Run service/adapter and focused schematic integration tests; expect all pass.
- [ ] Commit with `refactor(schematic): delegate document settings registration`.

### Task 3: Enforce architecture and public-contract stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_document_settings_architecture.py`

- [ ] Write failing architecture tests for service purity, adapter isolation, and the 300-line limit.
- [ ] Add both modules to the architecture policy and run the checker.
- [ ] Compare exact full-server metadata for the three tools against `main` and run the committed tool-surface snapshot.
- [ ] Commit with `test(architecture): guard document settings boundaries`.

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-23-schematic-document-settings-service.md`

- [ ] Run focused service/adapter coverage with the two new modules; require at least 83%.
- [ ] Run metadata, format, Ruff, mypy, scoped Pyright, architecture, workflow security, strict MkDocs, generated docs, snapshot, latency, Bandit, dependency audit, package build, Semgrep, OSV-Scanner, and full unit gates.
- [ ] Record exact surface equality, focused/full test counts, coverage, register spans, and security/package outcomes.
- [ ] Commit with `docs(architecture): record document settings evidence`.

### Task 5: Open, review, and merge the pull request

- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect all bot/agent comments, reviews, and GraphQL review threads.
- [ ] Address every actionable finding and rerun affected checks.
- [ ] Merge only after all required checks pass and the merge state is clean.
- [ ] Update `main` and remove the worktree and local/remote topic branch.
