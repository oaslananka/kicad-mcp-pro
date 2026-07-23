# Schematic Basic Authoring Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract five basic schematic authoring tools into a FastMCP-free service and a sub-300-line registration adapter without changing the public MCP surface.

**Architecture:** `kicad_mcp.schematic.basic_authoring` owns deterministic symbol, wire, label, and power-symbol orchestration behind injected callables. `kicad_mcp.tools.schematic_basic_authoring` retains FastMCP decorators and Pydantic validation. `tools.schematic.register()` remains the composition root.

**Tech Stack:** Python 3.13, FastMCP, Pydantic, pytest, Ruff, mypy, Pyright, existing architecture and tool-surface gates.

## Global Constraints

- Preserve exact names, descriptions, schemas, annotations, profiles, defaults, validation, messages, and result-line ordering.
- Preserve child-sheet targeting, grid defaults, library insertion, root UUID selection, project naming, warnings, transaction targets, and reload ordering.
- Keep the domain service free of FastMCP, server/connection state, GUI dependencies, KiCad IPC, and `tools.schematic` imports.
- Keep `tools.schematic_basic_authoring.register()` at or below 300 lines.
- Do not add runtime dependencies or close #434.

---

### Task 1: Extract the basic authoring service

**Files:**
- Create: `tests/unit/test_schematic_basic_authoring_service.py`
- Create: `src/kicad_mcp/schematic/basic_authoring.py`

**Interfaces:**
- Produces: `SchematicBasicAuthoringService`.
- Produces methods: `add_symbol`, `add_wire`, `add_label`, and `add_power_symbol`.
- Consumes injected target, parser, library, snapping, formatting, block-builder, transaction, UUID, and reload callables.

- [x] **Step 1: Write failing direct service tests**

Cover symbol success, missing symbol with suggestions, invalid units, library insertion, warnings and result ordering, wire targeting/snapping, label alias/error behavior, and delegated power-symbol success/failure.

- [x] **Step 2: Run and verify RED**

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_basic_authoring_service.py
```

Expected: collection failure because `kicad_mcp.schematic.basic_authoring` does not exist.

- [x] **Step 3: Implement the injected service**

Implement only the current observable orchestration. Keep Pydantic models out of the service and accept already validated primitive values.

- [x] **Step 4: Run and verify GREEN**

Run the command from Step 2. Expected: all tests pass.

- [x] **Step 5: Commit**

```bash
git add src/kicad_mcp/schematic/basic_authoring.py \
  tests/unit/test_schematic_basic_authoring_service.py
git commit -m "refactor(schematic): extract basic authoring service"
```

### Task 2: Add the thin registration adapter

**Files:**
- Create: `tests/unit/test_schematic_basic_authoring_registration.py`
- Create: `src/kicad_mcp/tools/schematic_basic_authoring.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicBasicAuthoringService`.
- Produces: `SchematicBasicAuthoringDependencies(service)`.
- Produces: `register(mcp, dependencies) -> None`.

- [x] **Step 1: Write failing registration tests**

Assert exact public names, descriptions, schemas, headless metadata, Pydantic validation, alias behavior, and argument delegation.

- [x] **Step 2: Run and verify RED**

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_basic_authoring_registration.py
```

Expected: collection failure because the adapter does not exist.

- [x] **Step 3: Implement and wire the adapter**

Construct the service in the composition root, register the adapter once, and remove the five nested legacy functions.

- [x] **Step 4: Run focused behavior tests**

```bash
uv run --all-extras pytest -q \
  tests/unit/test_schematic_basic_authoring_service.py \
  tests/unit/test_schematic_basic_authoring_registration.py \
  tests/integration/test_schematic_tools.py \
  tests/integration/test_schematic_extended.py
```

Expected: all tests pass.

- [x] **Step 5: Commit**

```bash
git add src/kicad_mcp/tools/schematic.py \
  src/kicad_mcp/tools/schematic_basic_authoring.py \
  tests/unit/test_schematic_basic_authoring_registration.py
git commit -m "refactor(schematic): delegate basic authoring registration"
```

### Task 3: Enforce architecture and surface stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_basic_authoring_architecture.py`

- [x] **Step 1: Write failing architecture tests**

Assert service/adapter tracking, service purity, adapter isolation, and the 300-line limit.

- [x] **Step 2: Extend the architecture checker**

Register both modules, keep only the service in `PURE_HELPERS`, add the adapter import guard, and enforce the line limit.

- [x] **Step 3: Verify public-surface stability**

```bash
uv run --all-extras python scripts/check_architecture_boundaries.py
uv run --all-extras pytest -q tests/integration/test_tool_surface_snapshot.py
corepack pnpm run docs:tools:check
```

Expected: all pass without snapshot regeneration.

- [x] **Step 4: Commit**

```bash
git add scripts/check_architecture_boundaries.py \
  tests/unit/test_schematic_basic_authoring_architecture.py
git commit -m "test(architecture): guard basic authoring boundaries"
```

### Task 4: Verify, publish, and review

- [x] Run metadata, format, lint, mypy, scoped strict Pyright, full unit, workflow security, strict docs, snapshot, focused coverage, and representative performance gates.
- [x] Record exact public-surface and registration line-count evidence.
- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect every bot/agent comment, review, and review thread; resolve actionable findings.
- [ ] Merge only after all required checks pass.


## Verification Evidence

- Exact full-server metadata for all five extracted tools matches `main`: names, descriptions, input schemas, and annotations are identical.
- `tests/integration/test_tool_surface_snapshot.py` passes without snapshot regeneration.
- The main schematic `register()` span decreased from 2,807 to 2,591 lines; the basic-authoring adapter `register()` spans 199 lines.
- Focused service, registration, and schematic integration coverage passed: 149 tests.
- The extracted service and adapter have 100% focused line coverage.
- The full unit suite passed with five expected skips and one pre-existing async-mock warning.
- Metadata, formatting, Ruff, mypy, scoped strict Pyright, architecture, generated tool documentation, workflow policy/security, strict MkDocs, tool-surface snapshot, and the committed MCP latency benchmark all pass.
- No runtime dependency, public tool contract, child-sheet targeting, grid default, transaction target, reload order, warning order, or backend-selection behavior changed.
