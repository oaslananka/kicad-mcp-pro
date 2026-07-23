# Schematic Connectivity Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move bus, bus-entry, and no-connect authoring from the schematic MCP monolith into the existing FastMCP-free basic-authoring service and thin adapter without changing the public surface.

**Architecture:** Extend `SchematicBasicAuthoringService` with three deterministic orchestration methods using the existing target, snap, transaction, reload, and append dependencies plus injected bus-entry and no-connect block builders. Extend the existing FastMCP adapter for validation and registration, then remove the legacy nested functions from the composition root.

**Tech Stack:** Python 3.13, FastMCP, Pydantic, pytest, Ruff, mypy, Pyright, existing architecture and tool-surface gates.

## Global Constraints

- Preserve exact tool names, descriptions, schemas, annotations, profiles, validation, defaults, result strings, and result ordering.
- Preserve child-sheet targeting and default structural-loss protection.
- Keep `schematic_basic_authoring.register()` at or below 300 lines.
- Keep the service FastMCP-free and free of server, connection, GUI, IPC, SWIG, and registry imports.
- Do not add dependencies or close #434.

---

### Task 1: Extend the basic-authoring service

**Files:**
- Modify: `tests/unit/test_schematic_basic_authoring_service.py`
- Modify: `src/kicad_mcp/schematic/basic_authoring.py`

**Interfaces:**
- Produces: `add_bus(x1_mm, y1_mm, x2_mm, y2_mm, snap_to_grid, sheet, sheet_file) -> str`.
- Produces: `add_bus_wire_entry(x_mm, y_mm, direction, snap_to_grid, sheet, sheet_file) -> str`.
- Produces: `add_no_connect(x_mm, y_mm, snap_to_grid, sheet, sheet_file) -> str`.
- Consumes injected `wire_block`, `bus_entry_block`, `no_connect_block`, target, snap, append, transaction, and reload callables.

- [ ] **Step 1: Write failing direct service tests**

Add tests that call each new method and assert the exact appended block, target path, snapped coordinates, default transaction guard, reload-first response, target detail, and snap notice.

- [ ] **Step 2: Run tests to verify RED**

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_basic_authoring_service.py
```

Expected: failures because the three methods and new injected block builders do not exist.

- [ ] **Step 3: Implement the minimal service methods**

Extend the wire-block callable to accept an optional kind, inject bus-entry and no-connect builders, and implement the three methods using the same flow as existing wire/label authoring.

- [ ] **Step 4: Run tests to verify GREEN**

Run the command from Step 2. Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/kicad_mcp/schematic/basic_authoring.py tests/unit/test_schematic_basic_authoring_service.py
git commit -m "refactor(schematic): extend basic authoring primitives"
```

### Task 2: Extend the thin registration adapter

**Files:**
- Modify: `tests/unit/test_schematic_basic_authoring_registration.py`
- Modify: `src/kicad_mcp/tools/schematic_basic_authoring.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes the three new service methods.
- Preserves public tools `sch_add_bus`, `sch_add_bus_wire_entry`, and `sch_add_no_connect`.

- [ ] **Step 1: Write failing registration tests**

Assert the three tool names, exact descriptions, schemas/defaults, validation, and delegation arguments.

- [ ] **Step 2: Run tests to verify RED**

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_basic_authoring_registration.py
```

Expected: failures because the adapter does not register the three tools.

- [ ] **Step 3: Register and compose the tools**

Inject `bus_entry_block` and `no_connect_block` into the service, register the tools in the existing adapter, and remove the three legacy nested functions and now-unused model imports.

- [ ] **Step 4: Run focused behavior tests**

```bash
uv run --all-extras pytest -q \
  tests/unit/test_schematic_basic_authoring_service.py \
  tests/unit/test_schematic_basic_authoring_registration.py \
  tests/integration/test_schematic_tools.py \
  tests/integration/test_schematic_extended.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/kicad_mcp/tools/schematic.py src/kicad_mcp/tools/schematic_basic_authoring.py \
  tests/unit/test_schematic_basic_authoring_registration.py
git commit -m "refactor(schematic): delegate connectivity primitive registration"
```

### Task 3: Verify boundaries and publish

**Files:**
- Modify: `docs/superpowers/plans/2026-07-23-schematic-connectivity-primitives.md`
- Existing checks: `tests/unit/test_schematic_basic_authoring_architecture.py`

- [ ] Verify the adapter `register()` span remains at or below 300 lines and the existing architecture checker passes.
- [ ] Compare full-server metadata for all three tools against `main`; require exact equality.
- [ ] Run focused line coverage and require all modified service/adapter lines to be covered.
- [ ] Run metadata, formatting, Ruff, mypy, scoped strict Pyright, full unit, workflow-security, strict MkDocs, snapshot, and latency benchmark gates.
- [ ] Record exact test, coverage, metadata, and line-count evidence in this plan.
- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect every bot/agent comment, review, and GraphQL review thread; resolve actionable findings.
- [ ] Squash merge only when all required checks are successful and the merge state is clean.
