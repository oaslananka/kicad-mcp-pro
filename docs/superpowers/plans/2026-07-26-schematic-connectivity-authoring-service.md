# Schematic Connectivity Authoring Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract schematic pin-terminal authoring, pin-to-pin routing, and junction repair into a FastMCP-independent service and thin adapter without changing the public MCP contract.

**Architecture:** `tools.schematic` remains the composition root and injects existing parsing, geometry, transaction, and reload helpers into `SchematicConnectivityAuthoringService`. A separate adapter owns the three public FastMCP functions and their decorators.

**Tech Stack:** Python 3.13, FastMCP, Pydantic, pytest, Ruff, mypy, Pyright.

## Global Constraints

- Preserve exact public tool names, signatures, docstrings, schemas, annotations, metadata, response strings, and transaction/reload behavior.
- Keep `run_auto_add_missing_junctions` in `tools.schematic` for fixer imports and monkeypatch seams.
- Domain service imports no FastMCP and no schematic registry module.
- Adapter `register()` stays at or below 300 lines.
- Work is delivered as reviewable test-first commits.

---

### Task 1: Lock architecture and MCP registration contracts

**Files:**
- Create: `tests/unit/test_schematic_connectivity_authoring_architecture.py`
- Create: `tests/unit/test_schematic_connectivity_authoring_registration.py`

**Interfaces:**
- Consumes: current full-server contracts for the three public tools.
- Produces: failing imports for the not-yet-created service adapter and explicit architecture expectations.

- [ ] **Step 1: Write the architecture test**

Assert that the future service and adapter are tracked by `scripts/check_architecture_boundaries.py`, the service imports neither FastMCP nor the monolith, the adapter does not import the monolith, adapter `register()` is at most 300 lines, and the composition root no longer defines the three nested functions.

- [ ] **Step 2: Write the adapter contract test**

Register the future adapter against a fake service. Assert exact tool names, descriptions, parameter schemas, output schemas, metadata, annotations, argument delegation, and returned strings.

- [ ] **Step 3: Run the tests and confirm red**

Run:

```bash
uv run --all-extras pytest -q \
  tests/unit/test_schematic_connectivity_authoring_architecture.py \
  tests/unit/test_schematic_connectivity_authoring_registration.py
```

Expected: collection fails because `kicad_mcp.tools.schematic_connectivity_authoring` does not exist.

- [ ] **Step 4: Commit the red contract tests**

```bash
git add tests/unit/test_schematic_connectivity_authoring_*.py
git commit -m "test(schematic): lock connectivity authoring extraction contract"
```

### Task 2: Define service behavior with direct unit tests

**Files:**
- Create: `tests/unit/test_schematic_connectivity_authoring_service.py`

**Interfaces:**
- Produces: behavior contract for `SchematicConnectivityAuthoringService` methods `add_pin_labels`, `route_wire_between_pins`, and `add_missing_junctions`.

- [ ] **Step 1: Add pin-label behavior tests**

Cover invalid connection records, missing references, missing pins, power-symbol fallback, signal labels, power terminals, dense terminal staggering, no-op output, target-specific transaction writes, and reload/target-detail output.

- [ ] **Step 2: Add routing behavior tests**

Cover missing references, missing pins, already-overlapping pins, successful routed segments, obstacle warning propagation, transactional writes, and reload output.

- [ ] **Step 3: Add junction-repair behavior test**

Assert the module-level repair callback runs before reload and the response order remains `reload + summary`.

- [ ] **Step 4: Run the service tests and confirm red**

Expected: collection fails because `kicad_mcp.schematic.connectivity_authoring` does not exist.

- [ ] **Step 5: Commit the red service tests**

```bash
git add tests/unit/test_schematic_connectivity_authoring_service.py
git commit -m "test(schematic): define connectivity authoring service behavior"
```

### Task 3: Implement the FastMCP-independent service

**Files:**
- Create: `src/kicad_mcp/schematic/connectivity_authoring.py`
- Test: `tests/unit/test_schematic_connectivity_authoring_service.py`

**Interfaces:**
- Produces: `SchematicConnectivityAuthoringService` with the three methods defined above.

- [ ] **Step 1: Add narrow Protocols and callable aliases**

Define target and bounding-box protocols plus typed callable fields for parsing, pin lookup, geometry, block creation, transactions, reload, and logging.

- [ ] **Step 2: Move pin-label orchestration**

Copy the existing behavior exactly and replace direct helper calls with injected dependencies.

- [ ] **Step 3: Move pin-routing orchestration**

Validate with `RouteWireBetweenPinsInput`, resolve pins, route around obstacles, append wire blocks transactionally, and preserve current messages.

- [ ] **Step 4: Move missing-junction orchestration**

Call the injected fixer, then reload, and return the existing combined response.

- [ ] **Step 5: Run service tests, Ruff, mypy, and Pyright**

All direct service tests and static checks must pass.

- [ ] **Step 6: Commit the service**

```bash
git add src/kicad_mcp/schematic/connectivity_authoring.py tests/unit/test_schematic_connectivity_authoring_service.py
git commit -m "refactor(schematic): extract connectivity authoring service"
```

### Task 4: Add adapter and delegate composition-root registration

**Files:**
- Create: `src/kicad_mcp/tools/schematic_connectivity_authoring.py`
- Modify: `src/kicad_mcp/tools/schematic.py`
- Modify: `scripts/check_architecture_boundaries.py`
- Test: `tests/unit/test_schematic_connectivity_authoring_architecture.py`
- Test: `tests/unit/test_schematic_connectivity_authoring_registration.py`

**Interfaces:**
- Consumes: `SchematicConnectivityAuthoringService`.
- Produces: unchanged public FastMCP tools and a smaller schematic composition root.

- [ ] **Step 1: Implement the thin adapter**

Copy exact public signatures and docstrings. Apply `headless_compatible` only to `sch_add_missing_junctions`. Delegate directly to the service.

- [ ] **Step 2: Compose the service in `tools.schematic`**

Inject all existing helpers, remove the three nested tools, and call `schematic_connectivity_authoring.register(...)` at the former registration location.

- [ ] **Step 3: Extend architecture guards**

Track the service as pure, prohibit adapter-to-monolith imports, and enforce the 300-line adapter limit.

- [ ] **Step 4: Run focused unit and integration tests**

Run new unit tests plus all existing pin-label, routing, junction, and fixer integration tests.

- [ ] **Step 5: Compare full-server MCP contracts**

Generate JSON for the three tools on `main` and the branch; require an empty diff and identical SHA-256 values.

- [ ] **Step 6: Commit adapter/delegation changes**

```bash
git add scripts/check_architecture_boundaries.py src/kicad_mcp/tools/schematic.py \
  src/kicad_mcp/tools/schematic_connectivity_authoring.py \
  tests/unit/test_schematic_connectivity_authoring_architecture.py \
  tests/unit/test_schematic_connectivity_authoring_registration.py
git commit -m "refactor(schematic): delegate connectivity authoring registration"
```

### Task 5: Repository verification and PR

**Files:**
- Modify only if generated artifacts intentionally require updates; otherwise expect no generated diff.

- [ ] **Step 1: Run generated-contract gates**

Run architecture, tool-contract, metadata, tools-reference, parity, and parity-regression checks.

- [ ] **Step 2: Run quality gates**

Run scoped Ruff format/check, full mypy, scoped Pyright, representative latency, package build/metadata, runtime policy, no-pcbnew, and strict docs.

- [ ] **Step 3: Run full unit suite**

Run `python scripts/run_pytest.py unit` and record the complete result.

- [ ] **Step 4: Push and create a PR**

The PR must reference #434 but must not close it unless the final composition-root register span is at or below 300 lines.
