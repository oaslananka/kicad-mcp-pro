# Schematic Back-Annotation Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Extract project hop-over settings and pin/gate swap intent behavior from FastMCP registration into a directly testable schematic domain service.

**Architecture:** Add one pure orchestration service and one thin FastMCP adapter. Keep `src/kicad_mcp/tools/schematic.py` as the composition root by injecting its existing project, symbol-library, and state-storage helpers.

**Tech Stack:** Python 3.13, FastMCP, pytest, Ruff, mypy, Pyright, existing architecture and metadata generators.

## Global Constraints

- Preserve all four public tool names, signatures, descriptions, schemas, annotations, profiles, defaults, and result strings.
- Preserve current project JSON and `.kicad-mcp` state-file behavior.
- Do not add runtime dependencies.
- Keep the new adapter `register()` function at or below 300 lines.
- Keep domain code independent of FastMCP and `tools.schematic`.

---

### Task 1: Add the FastMCP-free domain service

**Files:**
- Create: `src/kicad_mcp/schematic/back_annotation.py`
- Create: `tests/unit/test_schematic_back_annotation_service.py`

**Interfaces:**
- Produces: `SchematicBackAnnotationService.set_hop_over(enabled: bool) -> str`
- Produces: `SchematicBackAnnotationService.list_swappable_pins(component_ref: str) -> str`
- Produces: `SchematicBackAnnotationService.swap_pins(component_ref: str, pin_a: str, pin_b: str) -> str`
- Produces: `SchematicBackAnnotationService.swap_gates(component_ref: str, gate_a: int, gate_b: int) -> str`

- [x] **Step 1: Write failing service tests**

Cover missing/invalid project JSON, hop-over writes, numeric pin filtering/sorting, unit discovery, invalid candidates, and persisted pin/gate intent payloads.

- [x] **Step 2: Verify RED**

Run:

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_back_annotation_service.py
```

Expected: collection fails because `kicad_mcp.schematic.back_annotation` does not exist.

- [x] **Step 3: Implement the service**

Use injected callables and preserve the current strings and state payloads exactly. Keep a private payload builder so swap methods share candidate discovery without importing FastMCP.

- [x] **Step 4: Verify GREEN and types**

Run:

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_back_annotation_service.py
uv run --all-extras ruff check src/kicad_mcp/schematic/back_annotation.py tests/unit/test_schematic_back_annotation_service.py
uv run --all-extras pyright src/kicad_mcp/schematic/back_annotation.py
```

Expected: all pass with no type findings.

- [x] **Step 5: Commit**

```bash
git add src/kicad_mcp/schematic/back_annotation.py tests/unit/test_schematic_back_annotation_service.py
git commit -m "refactor(schematic): extract back-annotation service"
```

### Task 2: Add the thin FastMCP adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_back_annotation.py`
- Create: `tests/unit/test_schematic_back_annotation_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicBackAnnotationService`
- Produces: `SchematicBackAnnotationDependencies(service: SchematicBackAnnotationService)`
- Produces: `register(mcp: FastMCP, dependencies: SchematicBackAnnotationDependencies) -> None`

- [x] **Step 1: Write failing adapter tests**

Assert exact tool names, descriptions, defaults, required fields, annotations, headless metadata, validation, and delegation arguments.

- [x] **Step 2: Verify RED**

Run:

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_back_annotation_registration.py
```

Expected: collection fails because the adapter module does not exist.

- [x] **Step 3: Implement adapter and composition root**

Register the four existing signatures and inject current helpers from `schematic.py`. Delete the four nested tool implementations from the main `register()` function.

- [x] **Step 4: Verify adapter and focused integration behavior**

Run:

```bash
uv run --all-extras pytest -q \
  tests/unit/test_schematic_back_annotation_service.py \
  tests/unit/test_schematic_back_annotation_registration.py \
  tests/unit/test_kicad10_parity_tools.py \
  tests/integration/test_schematic_tools.py \
  tests/integration/test_schematic_extended.py
```

Expected: all pass.

- [x] **Step 5: Commit**

```bash
git add src/kicad_mcp/tools/schematic.py src/kicad_mcp/tools/schematic_back_annotation.py tests/unit/test_schematic_back_annotation_registration.py
git commit -m "refactor(schematic): delegate back-annotation registration"
```

### Task 3: Enforce architecture and contract preservation

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_back_annotation_architecture.py`

- [x] **Step 1: Write failing architecture tests**

Require the new service in `PURE_HELPERS`, forbid the adapter from importing `tools.schematic`, and require a 300-line adapter registration limit.

- [x] **Step 2: Verify RED**

Run:

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_back_annotation_architecture.py
```

Expected: failures for missing policy entries.

- [x] **Step 3: Extend the architecture checker**

Add the service and adapter paths, forbidden adapter import, pure-helper classification, and line limit.

- [x] **Step 4: Verify architecture and public surface**

Run:

```bash
uv run --all-extras pytest -q tests/unit/test_schematic_back_annotation_architecture.py
uv run --all-extras python scripts/check_architecture_boundaries.py
uv run --all-extras pytest -q tests/integration/test_tool_surface_snapshot.py
```

Compare full-server metadata for the four tools against `main`; expected result is exact equality.

- [x] **Step 5: Commit**

```bash
git add scripts/check_architecture_boundaries.py tests/unit/test_schematic_back_annotation_architecture.py
git commit -m "test(architecture): guard back-annotation boundaries"
```

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-23-schematic-back-annotation-service.md`

- [x] **Step 1: Run focused coverage**

```bash
uv run --all-extras pytest -q \
  tests/unit/test_schematic_back_annotation_service.py \
  tests/unit/test_schematic_back_annotation_registration.py \
  --cov=kicad_mcp.schematic.back_annotation \
  --cov=kicad_mcp.tools.schematic_back_annotation \
  --cov-report=term-missing
```

Expected: at least 83% and no uncovered new behavior branches left without justification.

- [x] **Step 2: Run repository quality gates**

```bash
corepack pnpm run check:meta
corepack pnpm run format:check
corepack pnpm run lint
corepack pnpm run typecheck
uv run --all-extras pyright src/kicad_mcp/schematic/back_annotation.py
corepack pnpm run check:workflows
DISABLE_MKDOCS_2_WARNING=true uv run --all-extras mkdocs build --strict
uv run --all-extras pytest -q -m benchmark tests/unit/test_benchmark_latency.py
corepack pnpm run check:security
corepack pnpm run package:check
uv run --all-extras python scripts/run_pytest.py unit
```

Expected: all pass; only existing documented warnings/skips may remain.

- [x] **Step 3: Record measured evidence**

Update this plan with service/adapter coverage, focused/full test results, public-surface equality, register spans, and security/package outcomes.

- [x] **Step 4: Commit evidence**

```bash
git add docs/superpowers/plans/2026-07-23-schematic-back-annotation-service.md
git commit -m "docs(architecture): record back-annotation evidence"
```


## Verification Evidence

- Exact full-server metadata for `sch_set_hop_over`, `sch_list_swappable_pins`, `sch_swap_pins`, and `sch_swap_gates` matches `main`; names, descriptions, input schemas, defaults, and annotations are identical.
- The committed tool-surface snapshot and generated tool documentation pass without regeneration.
- The main schematic `register()` span decreased from 2,498 to 2,403 lines; the back-annotation adapter `register()` spans 27 lines.
- Focused service, registration, architecture, KiCad 10 parity, and schematic integration verification passed: 156 tests.
- The extracted service and adapter have 100% focused line coverage.
- The full unit suite passed with five expected skips and the existing Windows-daemon async-mock warning.
- Metadata, formatting, Ruff, mypy, scoped strict Pyright, architecture, workflow policy/security, strict MkDocs, tool-surface snapshot, and the committed MCP latency benchmark all pass.
- Bandit reported no medium/high findings, pip-audit reported no known vulnerabilities, and source/wheel builds plus package metadata validation passed.
- No runtime dependency, public tool contract, experimental profile exposure, state filename, state payload, candidate ordering, project JSON behavior, or result string changed.

### Task 5: Open, review, and merge the pull request

- [ ] **Step 1: Push and open a professional English PR referencing #434**
- [ ] **Step 2: Inspect all bot/agent comments, reviews, and GraphQL review threads**
- [ ] **Step 3: Address every actionable finding and rerun affected checks**
- [ ] **Step 4: Merge only after all required checks pass and the merge state is clean**
- [ ] **Step 5: Update `main` and remove the worktree and local/remote topic branch**
