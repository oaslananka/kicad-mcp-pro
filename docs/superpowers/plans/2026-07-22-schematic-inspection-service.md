# Schematic Inspection Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Extract seven read-only schematic tools into a FastMCP-free inspection service and a sub-300-line registration adapter without changing the public MCP surface.

**Architecture:** `kicad_mcp.schematic.inspection` owns deterministic inspection behavior behind injected callables. `kicad_mcp.tools.schematic_inspection` owns MCP decorators and argument adaptation, while `tools.schematic.register()` only wires existing private dependencies into the new adapter.

**Tech Stack:** Python 3.13, FastMCP, pytest, Ruff, mypy, scoped Pyright, existing tool-surface snapshot and architecture checks.

## Global Constraints

- Preserve every public tool name, input schema, description, cache decorator, annotation, exception, and result string.
- Do not import FastMCP, `kicad_mcp.tools.schematic`, server state, connection state, `kipy`, `wx`, or `pcbnew` from the domain service.
- Keep `tools.schematic_inspection.register()` below 300 lines.
- Do not add runtime dependencies.
- Do not close #434 from this bounded tranche.

---

### Task 1: Pin the pure inspection-service behavior

**Files:**
- Create: `tests/unit/test_schematic_inspection_service.py`
- Create: `src/kicad_mcp/schematic/__init__.py`
- Create: `src/kicad_mcp/schematic/inspection.py`

**Interfaces:**
- Produces: `SchematicInspectionService`, constructed with parser, diagnostics, population, unit, and pin-position callables.
- Produces methods: `symbols`, `wires`, `labels`, `net_names`, `population_status`, `pin_positions`, and `power_flags`.

- [x] **Step 1: Write failing tests for each exact legacy result**

Create fixtures using in-memory parser data and assert exact strings, ordering,
formatting, empty diagnostics, missing-reference errors, unsupported-unit
responses, and population JSON formatting.

- [x] **Step 2: Run the service tests and verify RED**

Run:

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_inspection_service.py
```

Expected: collection failure because `kicad_mcp.schematic.inspection` does not
exist.

- [x] **Step 3: Implement the minimal injected service**

Implement typed callable aliases and an immutable service class. Copy only the
observable domain/formatting behavior from the seven existing tool bodies.

- [x] **Step 4: Run the service tests and verify GREEN**

Run the command from Step 2. Expected: all tests pass.

- [x] **Step 5: Commit**

```bash
git add src/kicad_mcp/schematic tests/unit/test_schematic_inspection_service.py
git commit -m "refactor(schematic): extract inspection domain service"
```

### Task 2: Add the thin registration adapter

**Files:**
- Create: `tests/unit/test_schematic_inspection_registration.py`
- Create: `src/kicad_mcp/tools/schematic_inspection.py`
- Modify: `src/kicad_mcp/tools/schematic.py:5434-6940`

**Interfaces:**
- Consumes: `SchematicInspectionService` from Task 1.
- Produces: `SchematicInspectionDependencies(resolve_target, service)`.
- Produces: `register(mcp: FastMCP, dependencies: SchematicInspectionDependencies) -> None`.

- [x] **Step 1: Write a failing registration test**

Construct a `FastMCP` server, register only the inspection adapter with fake
dependencies, and assert the seven exact public names plus the existing
headless/cache metadata behavior.

- [x] **Step 2: Run the registration test and verify RED**

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_inspection_registration.py
```

Expected: import failure because the adapter does not exist.

- [x] **Step 3: Implement the adapter under 300 lines**

Declare the existing decorators and docstrings on thin functions. Resolve paths
only where the existing tool accepted `sheet` or `sheet_file`, then delegate to
the service.

- [x] **Step 4: Wire the adapter from the monolith**

Construct `SchematicInspectionService` and `SchematicInspectionDependencies`
inside `tools.schematic.register()`, call the adapter registration once, and
remove the seven nested legacy function bodies.

- [x] **Step 5: Run focused registration and existing behavior tests**

```bash
uv run --all-extras pytest -q \
  tests/unit/test_schematic_inspection_registration.py \
  tests/integration/test_schematic_tools.py
```

Expected: all tests pass.

- [x] **Step 6: Commit**

```bash
git add src/kicad_mcp/tools/schematic.py \
  src/kicad_mcp/tools/schematic_inspection.py \
  tests/unit/test_schematic_inspection_registration.py
git commit -m "refactor(schematic): delegate inspection tool registration"
```

### Task 3: Enforce architecture and public-surface stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_inspection_architecture.py`
- Modify only if intentionally regenerated with no semantic change: `tests/integration/data/tool_surface_snapshot.json`

**Interfaces:**
- Consumes: the modules created in Tasks 1 and 2.
- Produces: architecture-policy failures for forbidden imports, cycles, adapter-to-monolith imports, or registration functions over 300 lines.

- [x] **Step 1: Write failing architecture tests**

Assert the domain module is in `DOMAIN_MODULES`, is in `PURE_HELPERS`, the
adapter cannot import `tools.schematic`, and its `register()` span is at most
300 lines.

- [x] **Step 2: Run and verify RED**

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_inspection_architecture.py
```

Expected: failure because the architecture checker does not yet know the new
modules.

- [x] **Step 3: Extend the architecture checker**

Add both module paths, keep only the domain service in `PURE_HELPERS`, and add a
specific adapter-to-monolith import guard plus the 300-line registration limit.

- [x] **Step 4: Verify architecture and tool-surface stability**

```bash
uv run --all-extras python scripts/check_architecture_boundaries.py
uv run --all-extras pytest -q tests/integration/test_tool_surface_snapshot.py
corepack pnpm run docs:tools:check
```

Expected: all pass with no snapshot regeneration.

- [x] **Step 5: Commit**

```bash
git add scripts/check_architecture_boundaries.py \
  tests/unit/test_schematic_inspection_architecture.py
git commit -m "test(architecture): guard schematic inspection boundaries"
```

### Task 4: Verify and publish the bounded tranche

**Files:**
- Modify: `docs/superpowers/specs/2026-07-22-schematic-inspection-service-design.md` only if verification reveals ambiguity.
- Modify: `docs/superpowers/plans/2026-07-22-schematic-inspection-service.md` to mark completed checkboxes.

**Interfaces:**
- Produces: a PR that references #434 and explicitly documents the remaining tranches.

- [x] **Step 1: Run repository quality gates**

```bash
corepack pnpm run check:meta
corepack pnpm run format:check
corepack pnpm run lint
corepack pnpm run typecheck
uv run --all-extras pyright src/kicad_mcp/schematic/inspection.py
uv run --all-extras python scripts/run_pytest.py unit
corepack pnpm run check:workflows
DISABLE_MKDOCS_2_WARNING=true uv run --all-extras mkdocs build --strict
```

Expected: all pass.

- [x] **Step 2: Compare public surface and performance evidence**

Run the tool-surface snapshot test and representative schematic benchmark tests;
record that no tool entries changed and no material latency regression occurred.

- [ ] **Step 3: Commit final plan status and push**

```bash
git add docs/superpowers/plans/2026-07-22-schematic-inspection-service.md
git commit -m "docs(architecture): record schematic inspection tranche evidence"
git push -u origin feat/434-schematic-domain-services
```

- [ ] **Step 4: Open and evaluate the PR**

Open a professional English PR with `Refs #434`, inspect all bot/agent comments,
reviews, and review threads, fix actionable findings, and merge only after every
required check passes.

## Verification Evidence

- Full unit suite completed successfully with five expected skips and one existing async-mock warning.
- Focused schematic integration and latency coverage completed with 71 passing tests.
- The seven extracted tools have byte-for-byte equivalent descriptions, input schemas, and annotations on `main` and this branch.
- `tests/integration/test_tool_surface_snapshot.py` passed without regenerating the public tool snapshot.
- `schematic.register()` decreased from 3,415 to 3,273 lines; the new inspection adapter registers the extracted surface in 78 lines.
- Metadata, formatting, Ruff, mypy, scoped Pyright, architecture, generated tool docs, workflow policy/security, and strict MkDocs checks passed.
- The repository-wide strict Pyright backlog is unchanged from `main`; this tranche introduces no new errors, and the new pure domain module passes scoped Pyright with zero findings.
