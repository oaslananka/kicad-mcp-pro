# Schematic Lifecycle Authoring Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the final nested schematic lifecycle tools into a FastMCP-independent service and thin adapter while preserving exact contracts and fixer seams.

**Architecture:** The schematic composition root injects existing helpers into `SchematicLifecycleAuthoringService`; a separate adapter owns public FastMCP signatures, decorators, and docstrings. `run_auto_annotate` remains in `tools.schematic`.

**Tech Stack:** Python 3.13, FastMCP, Pydantic, pytest, Ruff, mypy, Pyright.

## Global Constraints

- Preserve exact public names, schemas, metadata, annotations, exceptions, response strings, and write/reload ordering.
- Preserve the triple `@mcp.tool()` annotation registration seam.
- Keep `run_auto_annotate` importable from `tools.schematic`.
- Service imports no FastMCP or schematic registry.
- Adapter `register()` remains at or below 300 lines.

---

### Task 1: Lock adapter and architecture contracts

**Files:**
- Create: `tests/unit/test_schematic_lifecycle_authoring_architecture.py`
- Create: `tests/unit/test_schematic_lifecycle_authoring_registration.py`

- [ ] Write tests asserting future architecture registrations, forbidden imports, adapter line limit, composition delegation, and retained `run_auto_annotate` seam.
- [ ] Register the future adapter with a fake service and assert exact names, descriptions, schemas, metadata, raw annotations, arguments, exceptions, and return values.
- [ ] Run the tests and confirm collection fails because the adapter module does not exist.
- [ ] Commit as `test(schematic): lock lifecycle authoring extraction contract`.

### Task 2: Define service behavior

**Files:**
- Create: `tests/unit/test_schematic_lifecycle_authoring_service.py`

- [ ] Test jumper pin bounds, snapping, naming, placement payload, transaction, reload, and snap-note response ordering.
- [ ] Test annotation validation, sorting delegation, prefix counters, reference replacement, transaction, and reload response.
- [ ] Test direct reload delegation.
- [ ] Run and confirm the missing service module produces the expected red failure.
- [ ] Commit as `test(schematic): define lifecycle authoring service behavior`.

### Task 3: Implement service

**Files:**
- Create: `src/kicad_mcp/schematic/lifecycle_authoring.py`

- [ ] Add typed callable dependencies and `SchematicLifecycleAuthoringService`.
- [ ] Move jumper orchestration without changing messages or helper ordering.
- [ ] Move annotation orchestration without changing Pydantic validation, sorting, prefix allocation, replacement, or reload ordering.
- [ ] Add reload delegation.
- [ ] Run service tests, Ruff, mypy, and Pyright.
- [ ] Commit as `refactor(schematic): extract lifecycle authoring service`.

### Task 4: Add adapter and composition delegation

**Files:**
- Create: `src/kicad_mcp/tools/schematic_lifecycle_authoring.py`
- Modify: `src/kicad_mcp/tools/schematic.py`
- Modify: `scripts/check_architecture_boundaries.py`
- Test: lifecycle architecture and registration tests

- [ ] Copy exact public signatures, docstrings, and decorators into the adapter.
- [ ] Construct the service from existing helpers and delegate registration at the original location.
- [ ] Remove only the three nested public tools; retain `run_auto_annotate`.
- [ ] Extend architecture policy registries.
- [ ] Run focused unit and existing integration tests.
- [ ] Generate old/new full-server contract JSON and require identical SHA-256 values.
- [ ] Commit as `refactor(schematic): delegate lifecycle authoring registration`.

### Task 5: Verify and open PR

- [ ] Run architecture, tool-contract, metadata, tools-reference, parity, and regression gates.
- [ ] Run focused coverage above 83%, representative latency, scoped Ruff, full mypy, scoped Pyright, package metadata, runtime, no-pcbnew, and strict docs.
- [ ] Run the full unit suite and record exit code.
- [ ] Push and open a PR referencing but not closing #434 because composition wiring will still require a final split.
