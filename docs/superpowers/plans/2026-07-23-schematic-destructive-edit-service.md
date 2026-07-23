# Schematic Destructive Edit Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract five explicit wire, symbol, and label edit tools into a FastMCP-free service and a sub-300-line registration adapter without changing the public MCP surface or structural-loss policy.

**Architecture:** `kicad_mcp.schematic.destructive_edit` owns deterministic edit orchestration behind injected parsers and transaction callables. `kicad_mcp.tools.schematic_destructive_edit` owns public decorators and Pydantic argument validation. `tools.schematic.register()` remains the composition root.

**Tech Stack:** Python 3.13, FastMCP, Pydantic, pytest, Ruff, mypy, Pyright, existing architecture and tool-surface checks.

## Global Constraints

- Preserve exact names, descriptions, schemas, annotations, profiles, validation, matching tolerances, and result strings.
- Preserve `allow_node_loss=True` only for wire, symbol, and label deletion.
- Preserve transaction/checkpoint behavior, reload ordering, and exception behavior.
- Keep the domain service free of FastMCP, server/connection state, GUI dependencies, and `tools.schematic` imports.
- Keep `tools.schematic_destructive_edit.register()` at or below 300 lines.
- Do not add runtime dependencies or close #434.

---

### Task 1: Extract the destructive edit service

**Files:**
- Create: `tests/unit/test_schematic_destructive_edit_service.py`
- Create: `src/kicad_mcp/schematic/destructive_edit.py`

**Interfaces:**
- Produces: `SchematicDestructiveEditService`.
- Produces methods: `delete_wire`, `delete_symbol`, `delete_label`, `move_label`, and `modify_label`.
- Consumes injected path, parser, formatting, grid, transaction, and reload callables.

- [x] **Step 1: Write failing direct service tests**

Cover successful and missing/ambiguous wire deletion, symbol deletion with attached-wire counts, label deletion grid matching, label move snap/rotation behavior, label justification changes, and exact `allow_node_loss` flags.

- [x] **Step 2: Run and verify RED**

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_destructive_edit_service.py
```

Expected: collection failure because `kicad_mcp.schematic.destructive_edit` does not exist.

- [x] **Step 3: Implement the injected service**

Move only observable orchestration and deterministic text-edit behavior. Preserve the current 0.05 mm label tolerance and first-match semantics.

- [x] **Step 4: Run and verify GREEN**

Run the command from Step 2. Expected: all tests pass.

- [x] **Step 5: Commit**

```bash
git add src/kicad_mcp/schematic/destructive_edit.py \
  tests/unit/test_schematic_destructive_edit_service.py
git commit -m "refactor(schematic): extract destructive edit service"
```

### Task 2: Add the thin registration adapter

**Files:**
- Create: `tests/unit/test_schematic_destructive_edit_registration.py`
- Create: `src/kicad_mcp/tools/schematic_destructive_edit.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicDestructiveEditService`.
- Produces: `SchematicDestructiveEditDependencies(service)`.
- Produces: `register(mcp, dependencies) -> None`.

- [x] **Step 1: Write failing registration tests**

Assert exact public names, descriptions, schemas, annotations, validation, and argument delegation.

- [x] **Step 2: Run and verify RED**

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_destructive_edit_registration.py
```

Expected: collection failure because the adapter does not exist.

- [x] **Step 3: Implement and wire the adapter**

Construct the service in the composition root, register the adapter once, and remove the five nested legacy functions.

- [x] **Step 4: Run focused behavior tests**

```bash
uv run --all-extras pytest -q \
  tests/unit/test_schematic_destructive_edit_service.py \
  tests/unit/test_schematic_destructive_edit_registration.py \
  tests/integration/test_schematic_tools.py \
  tests/integration/test_schematic_extended.py
```

Expected: all tests pass.

- [x] **Step 5: Commit**

```bash
git add src/kicad_mcp/tools/schematic.py \
  src/kicad_mcp/tools/schematic_destructive_edit.py \
  tests/unit/test_schematic_destructive_edit_registration.py
git commit -m "refactor(schematic): delegate destructive edit registration"
```

### Task 3: Enforce architecture and surface stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_destructive_edit_architecture.py`

- [x] **Step 1: Write failing architecture tests**

Assert service/adapter tracking, domain purity, adapter isolation, and the 300-line limit.

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
  tests/unit/test_schematic_destructive_edit_architecture.py
git commit -m "test(architecture): guard destructive edit boundaries"
```

### Task 4: Verify, publish, and review

- [x] Run metadata, format, lint, mypy, scoped strict Pyright, full unit, workflow security, strict docs, snapshot, and representative performance gates.
- [x] Record exact public-surface, transaction-flag, and registration line-count evidence.
- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect every bot/agent comment, review, and review thread; resolve actionable findings.
- [ ] Merge only after all required checks pass.


## Verification Evidence

- Exact full-server metadata for all five extracted tools matches `main`: names, descriptions, input schemas, and annotations are identical.
- `tests/integration/test_tool_surface_snapshot.py` passes without snapshot regeneration.
- The main schematic `register()` span decreased from 3,093 to 2,807 lines; the destructive-edit adapter `register()` spans 69 lines.
- Focused service, registration, and schematic integration coverage passed: 150 tests; the extracted service and adapter have 100% focused line coverage.
- The full unit suite passed with five expected skips and one pre-existing async-mock warning.
- Deletion tests prove `allow_node_loss=True` remains limited to wire, symbol, and label deletion; label movement and justification keep the default structural-loss guard.
- Metadata, formatting, Ruff, mypy, scoped strict Pyright, architecture, generated tool documentation, workflow policy/security, strict MkDocs, tool-surface snapshot, and the committed MCP latency benchmark all pass.
- No runtime dependency, public tool contract, matching tolerance, reload order, transaction boundary, or backend-selection behavior changed.
