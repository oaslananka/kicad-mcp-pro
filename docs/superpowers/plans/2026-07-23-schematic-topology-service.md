# Schematic Topology Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract four sheet-hierarchy and connectivity tools into a FastMCP-free topology service and a sub-300-line registration adapter without changing the public MCP surface.

**Architecture:** `kicad_mcp.schematic.topology` owns deterministic result construction behind injected callables. `kicad_mcp.tools.schematic_topology` owns public decorators and Pydantic argument validation. `tools.schematic.register()` only supplies existing private dependencies.

**Tech Stack:** Python 3.13, FastMCP, Pydantic, pytest, Ruff, mypy, existing architecture and public-surface gates.

## Global Constraints

- Preserve all public names, schemas, descriptions, annotations, messages, ordering, and validation behavior.
- Keep the domain service free of FastMCP, connection state, GUI dependencies, and `tools.schematic` imports.
- Keep `tools.schematic_topology.register()` at or below 300 lines.
- Do not change connectivity algorithms or mutation behavior.
- Do not close #434.

---

### Task 1: Extract the pure topology service

**Files:**
- Create: `tests/unit/test_schematic_topology_service.py`
- Create: `src/kicad_mcp/schematic/topology.py`

- [ ] Write failing direct tests for hierarchy listing, sheet details, connectivity summaries, net tracing, diagnostics, warnings, and missing results.
- [ ] Run the tests and verify they fail because the module is absent.
- [ ] Implement `SchematicTopologyService` with injected loader, diagnostics, connectivity, child discovery, parser, and warning callables.
- [ ] Run the tests and verify they pass.
- [ ] Commit the service and tests.

### Task 2: Add the thin registration adapter

**Files:**
- Create: `tests/unit/test_schematic_topology_registration.py`
- Create: `src/kicad_mcp/tools/schematic_topology.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

- [ ] Write failing registration tests for exact names, descriptions, schemas, validation, and delegation.
- [ ] Implement the adapter and wire it from the composition root.
- [ ] Remove the four legacy nested tool bodies.
- [ ] Run focused registration and schematic integration tests.
- [ ] Commit the adapter tranche.

### Task 3: Enforce architecture and surface stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_topology_architecture.py`

- [ ] Write failing architecture tests for module tracking, purity, monolith-import prevention, and the 300-line limit.
- [ ] Extend the architecture checker.
- [ ] Verify the public snapshot and generated tool docs remain unchanged.
- [ ] Commit the architecture guard.

### Task 4: Verify, publish, and review

- [ ] Run metadata, format, lint, mypy, scoped Pyright, full unit, workflow-security, strict docs, snapshot, and representative performance gates.
- [ ] Record line-count and exact public-surface evidence.
- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect all bot/agent comments, reviews, and review threads; resolve actionable findings.
- [ ] Merge only after all required checks pass.
