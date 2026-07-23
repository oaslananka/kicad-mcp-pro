# Schematic Symbol Mutation Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Extract four non-destructive symbol property and placement tools into a FastMCP-free service and a sub-300-line registration adapter without changing the public MCP surface.

**Architecture:** `kicad_mcp.schematic.symbol_mutation` owns result composition and move orchestration behind injected callables. `kicad_mcp.tools.schematic_symbol_mutation` owns MCP decorators and `MoveSymbolInput` validation. `tools.schematic.register()` remains the composition root.

**Tech Stack:** Python 3.13, FastMCP, Pydantic, pytest, Ruff, mypy, Pyright, existing architecture and tool-surface checks.

## Global Constraints

- Preserve exact public names, descriptions, schemas, annotations, profiles, validation, and output strings.
- Preserve backend selection, transaction/checkpoint behavior, and reload ordering.
- Keep the domain service free of FastMCP, connection state, GUI dependencies, and `tools.schematic` imports.
- Keep `tools.schematic_symbol_mutation.register()` at or below 300 lines.
- Do not add runtime dependencies or close #434.

---

### Task 1: Extract the pure symbol mutation service

**Files:**
- Create: `tests/unit/test_schematic_symbol_mutation_service.py`
- Create: `src/kicad_mcp/schematic/symbol_mutation.py`

**Interfaces:**
- Produces: `SchematicSymbolMutationService`.
- Produces methods: `update_properties`, `set_dnp`, and `move_symbol`.
- Consumes injected property update, DNP update, reload, snap, transaction, lookup, and block-shift callables.

- [x] **Step 1: Write failing direct service tests**

Cover exact update/DNP output composition, move success with and without a snap notice, missing references, shift deltas, transaction flags, and reload ordering.

- [x] **Step 2: Run the service tests and verify RED**

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_symbol_mutation_service.py
```

Expected: collection failure because `kicad_mcp.schematic.symbol_mutation` does not exist.

- [x] **Step 3: Implement the injected service**

Add typed protocols and an immutable service class. Copy only the observable orchestration currently present in the four nested tool bodies.

- [x] **Step 4: Run the service tests and verify GREEN**

Run the command from Step 2. Expected: all tests pass.

- [x] **Step 5: Commit**

```bash
git add src/kicad_mcp/schematic/symbol_mutation.py \
  tests/unit/test_schematic_symbol_mutation_service.py
git commit -m "refactor(schematic): extract symbol mutation service"
```

### Task 2: Add the thin registration adapter

**Files:**
- Create: `tests/unit/test_schematic_symbol_mutation_registration.py`
- Create: `src/kicad_mcp/tools/schematic_symbol_mutation.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicSymbolMutationService`.
- Produces: `SchematicSymbolMutationDependencies(service)`.
- Produces: `register(mcp, dependencies) -> None`.

- [x] **Step 1: Write failing registration tests**

Assert the four exact public names, descriptions, schemas, headless metadata, Pydantic validation, alias behavior, and argument delegation.

- [x] **Step 2: Run and verify RED**

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_symbol_mutation_registration.py
```

Expected: collection failure because the adapter does not exist.

- [x] **Step 3: Implement and wire the adapter**

Construct the service in `tools.schematic.register()`, register the adapter once, and remove the four legacy nested functions.

- [x] **Step 4: Run focused behavior tests**

```bash
uv run --all-extras pytest -q \
  tests/unit/test_schematic_symbol_mutation_registration.py \
  tests/unit/test_schematic_population_status.py \
  tests/integration/test_schematic_tools.py \
  tests/integration/test_schematic_extended.py
```

Expected: all tests pass.

- [x] **Step 5: Commit**

```bash
git add src/kicad_mcp/tools/schematic.py \
  src/kicad_mcp/tools/schematic_symbol_mutation.py \
  tests/unit/test_schematic_symbol_mutation_registration.py
git commit -m "refactor(schematic): delegate symbol mutation registration"
```

### Task 3: Enforce architecture and surface stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_symbol_mutation_architecture.py`

**Interfaces:**
- Produces architecture failures for forbidden imports, cycles, adapter-to-monolith imports, or a registration function over 300 lines.

- [x] **Step 1: Write failing architecture tests**

Assert domain/adapter tracking, domain purity, adapter isolation, and the 300-line limit.

- [x] **Step 2: Extend the architecture checker**

Add both modules, keep only the service in `PURE_HELPERS`, add the adapter import guard, and register the line limit.

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
  tests/unit/test_schematic_symbol_mutation_architecture.py
git commit -m "test(architecture): guard symbol mutation boundaries"
```

### Task 4: Verify, publish, and review

- [x] Run metadata, format, lint, mypy, scoped strict Pyright, full unit, workflow security, strict docs, snapshot, and representative performance gates.
- [x] Record exact public-surface and registration line-count evidence.
- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect every bot/agent comment, review, and review thread; resolve actionable findings.
- [ ] Merge only after all required checks pass.


## Verification Evidence

- Exact full-server metadata for `sch_update_properties`, `sch_set_dnp`, `sch_modify_property`, and `sch_move_symbol` matches `main`: names, descriptions, input schemas, annotations, and profiles are unchanged.
- `tests/integration/test_tool_surface_snapshot.py` passes without regeneration.
- The main schematic `register()` span decreased from 3,145 to 3,093 lines; the new adapter `register()` spans 52 lines.
- The focused service, registration, population, and schematic integration suite completed with 148 passing tests.
- The full unit suite completed successfully with five expected skips and one pre-existing async-mock warning.
- Metadata, formatting, Ruff, mypy, scoped strict Pyright for the pure service, architecture, generated tool documentation, workflow policy/security, strict MkDocs, and the committed MCP latency benchmark all pass.
- Backend selection, transaction/checkpoint behavior, reload ordering, validation, and output strings remain unchanged.
